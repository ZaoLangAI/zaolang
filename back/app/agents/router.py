"""Provider routing.

Hard eligibility — capability, tier support, enabled state, latency budget —
is a plain code filter: a provider that physically cannot serve this
operation or tier must never be picked, no matter who decides. Choosing the
winner among the *eligible* candidates is delegated to the `intent_router`
LLM agent (`app.agents.intent_router.select_provider`): it is handed every
eligible candidate's declared capability plus its observed success
rate/latency/cost, and returns which one to use and why.

There is no fallback formula. If the agent is unavailable, degraded, or
names a provider outside the eligible set, `route()` reports no selection —
exactly as if there had been no eligible provider at all — and the caller
fails the job with credits released rather than silently reverting to a
rule of thumb.

Order of evaluation, applied identically for every job:

1. capability filter  — can this provider perform the operation and tier at all
2. availability filter — enabled, within budget, not already tried and
   failed earlier in this same job
3. LLM selection       — the agent picks one eligible candidate and explains why
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import intent_router
from app.models import ProviderStat
from app.models.enums import Operation, ProviderKind, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import ProviderConfig
from app.providers import fake
from app.providers.base import ProviderCapability
from app.providers.media_endpoints import dynamic_capabilities

# The two routes the product ships with, always present regardless of what an
# operator has configured. Real (database-configured) media routes are
# layered on top at request time by `build_catalog` — see its docstring for
# why that composition happens outside this module.
PROVIDER_CATALOG: dict[str, ProviderCapability] = {
    "fake_open_workflow": ProviderCapability(
        name="fake_open_workflow",
        kind=ProviderKind.OPEN_WORKFLOW,
        operations=frozenset(
            {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
        ),
        tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD}),
        quality_prior=0.72,
        typical_latency_ms=9_000,
        unit_cost_minor=2,
        model_or_workflow="comfy-sdxl-base@1.4.0",
        provider_factory=lambda: fake.get_provider("fake_open_workflow"),
    ),
    "fake_paid_api": ProviderCapability(
        name="fake_paid_api",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset(
            {
                Operation.TEXT_TO_IMAGE,
                Operation.TEXT_TO_VIDEO,
                Operation.IMAGE_TO_VIDEO,
                Operation.VIDEO_TO_VIDEO,
            }
        ),
        tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
        quality_prior=0.9,
        typical_latency_ms=22_000,
        unit_cost_minor=18,
        model_or_workflow="paid-video-v3",
        provider_factory=lambda: fake.get_provider("fake_paid_api"),
    ),
}


def build_catalog(session: Session) -> dict[str, ProviderCapability]:
    """The static fakes plus every enabled database-configured media route.

    Built fresh per call — like every other config-driven lookup in this
    codebase — so an operator adding an endpoint at `/admin/models` takes
    effect on the very next job, not after a restart.
    """
    return {**PROVIDER_CATALOG, **dynamic_capabilities(session)}


@dataclass
class Candidate:
    """One row of the router's decision trace.

    Purely informational once past the eligibility filter — these fields
    describe a candidate to the LLM and to the ops replay console, they no
    longer feed a scoring formula.
    """

    provider: str
    eligible: bool = True
    filter_reason: str | None = None
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    effective_cost: int = 0

    def to_trace(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class RoutingDecision:
    selected: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    catalog: dict[str, ProviderCapability] = field(default_factory=dict)

    @property
    def capability(self) -> ProviderCapability | None:
        return self.catalog.get(self.selected.provider) if self.selected else None

    @property
    def provider(self):  # type: ignore[no-untyped-def]
        capability = self.capability
        return capability.provider_factory() if capability else None

    def trace(self) -> list[dict[str, object]]:
        return [c.to_trace() for c in self.candidates]


def route(
    session: Session,
    *,
    operation: str,
    quality_tier: str,
    max_latency_ms: int | None = None,
    exclude_providers: Iterable[str] | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
) -> RoutingDecision:
    provider_config = config_service.get_typed(session, "providers", ProviderConfig)
    catalog = build_catalog(session)
    stats = _load_stats(session, operation, quality_tier)
    excluded = set(exclude_providers or ())

    candidates: list[Candidate] = []
    for name, capability in sorted(catalog.items()):
        candidate = Candidate(provider=name)

        if operation not in capability.operations:
            candidate.eligible = False
            candidate.filter_reason = "operation_not_supported"
            candidates.append(candidate)
            continue
        if quality_tier not in capability.tiers:
            candidate.eligible = False
            candidate.filter_reason = "tier_not_supported"
            candidates.append(candidate)
            continue

        # `providers` config only ever describes the two built-in fakes; a
        # database-configured media route's on/off switch is its own
        # `enabled` flag, already applied by `build_catalog` before this
        # loop ever sees it.
        setting = provider_config.providers.get(name)
        if name in PROVIDER_CATALOG and (setting is None or not setting.enabled):
            candidate.eligible = False
            candidate.filter_reason = "provider_disabled"
            candidates.append(candidate)
            continue
        if max_latency_ms is not None and capability.typical_latency_ms > max_latency_ms:
            candidate.eligible = False
            candidate.filter_reason = "latency_budget_exceeded"
            candidates.append(candidate)
            continue
        if name in excluded:
            candidate.eligible = False
            candidate.filter_reason = "previously_failed_this_job"
            candidates.append(candidate)
            continue

        retry_amplification = setting.retry_amplification if setting is not None else 1.2
        stat = stats.get(name)
        success_rate = _success_rate(stat, provider_config)
        # Failures are not free: a provider that fails a third of the time
        # really costs about 1.5 attempts per success. Still shown to the
        # LLM (and the replay console) even though nothing here ranks by it
        # any more.
        candidate.effective_cost = int(
            capability.unit_cost_minor * retry_amplification / max(success_rate, 0.05)
        )
        candidate.success_rate = round(success_rate, 4)
        candidate.avg_latency_ms = _avg_latency_ms(stat, capability)
        candidates.append(candidate)

    eligible = [c for c in candidates if c.eligible]
    if not eligible:
        reasons = {c.filter_reason for c in candidates if c.filter_reason}
        return RoutingDecision(
            selected=None,
            candidates=candidates,
            reason=f"no_eligible_provider:{','.join(sorted(r for r in reasons if r))}",
            catalog=catalog,
        )

    # Deterministic ordering for the trace and for what the LLM is shown —
    # independent of which one it ends up picking.
    eligible.sort(key=lambda c: c.provider)

    outcome = intent_router.select_provider(
        session,
        operation=operation,
        quality_tier=quality_tier,
        candidates=[_candidate_payload(c, catalog[c.provider]) for c in eligible],
        job_id=job_id,
        user_id=user_id,
    )
    selected_name = outcome.data.get("selected_provider")
    winner = next((c for c in eligible if c.provider == selected_name), None)
    if outcome.degraded or winner is None:
        return RoutingDecision(
            selected=None,
            candidates=candidates,
            reason="llm_selection_unavailable",
            catalog=catalog,
        )

    rationale = outcome.data.get("rationale")
    reason = f"llm_selected:{rationale}" if isinstance(rationale, str) and rationale else "llm_selected"
    return RoutingDecision(selected=winner, candidates=candidates, reason=reason, catalog=catalog)


def _candidate_payload(candidate: Candidate, capability: ProviderCapability) -> dict[str, Any]:
    return {
        "provider": candidate.provider,
        "kind": capability.kind.value,
        "quality_prior": capability.quality_prior,
        "success_rate": candidate.success_rate,
        "avg_latency_ms": candidate.avg_latency_ms,
        "effective_cost": candidate.effective_cost,
    }


def _load_stats(session: Session, operation: str, quality_tier: str) -> dict[str, ProviderStat]:
    rows = session.scalars(
        select(ProviderStat).where(
            ProviderStat.operation == operation, ProviderStat.quality_tier == quality_tier
        )
    )
    return {row.provider: row for row in rows}


def _success_rate(stat: ProviderStat | None, config: ProviderConfig) -> float:
    """Falls back to a conservative prior until there is enough evidence.

    Without this, a provider with a single lucky success would look as
    trustworthy as one with hundreds of reliable runs.
    """
    if stat is None or stat.attempts < config.minimum_samples_for_stats:
        return config.conservative_prior_success_rate
    return max(0.01, min(1.0, stat.successes / stat.attempts))


def _avg_latency_ms(stat: ProviderStat | None, capability: ProviderCapability) -> int:
    if stat is not None and stat.attempts > 0:
        return int(stat.total_latency_ms / stat.attempts)
    return capability.typical_latency_ms


def record_attempt_outcome(
    session: Session,
    *,
    provider: str,
    operation: str,
    quality_tier: str,
    succeeded: bool,
    latency_ms: int,
    cost_minor: int,
) -> None:
    """Feeds real outcomes back into the statistics the router reads."""
    stat = session.scalar(
        select(ProviderStat).where(
            ProviderStat.provider == provider,
            ProviderStat.operation == operation,
            ProviderStat.quality_tier == quality_tier,
        )
    )
    if stat is None:
        stat = ProviderStat(provider=provider, operation=operation, quality_tier=quality_tier)
        session.add(stat)
        session.flush()

    stat.attempts += 1
    stat.successes += 1 if succeeded else 0
    stat.total_latency_ms += latency_ms
    stat.total_cost_minor += cost_minor
    session.flush()
