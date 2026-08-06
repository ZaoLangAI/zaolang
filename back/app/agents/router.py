"""Provider routing.

Deliberately rule-based, not a model. The first version must be explainable:
every candidate is scored by a fixed formula and every rejection records why,
so an operator can replay any decision after the fact.

Order of evaluation, applied identically for every job:

1. capability filter — can this provider perform the operation and tier at all
2. availability filter — enabled, within its daily limit
3. score          — weighted quality / latency / cost / reliability
4. tie-break      — lower effective cost, then stable provider name
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProviderStat
from app.models.enums import Operation, ProviderKind, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import ProviderConfig, RoutingWeights
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
    provider: str
    eligible: bool = True
    filter_reason: str | None = None
    quality_score: float = 0.0
    latency_score: float = 0.0
    cost_score: float = 0.0
    reliability_score: float = 0.0
    total_score: float = 0.0
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
) -> RoutingDecision:
    weights = config_service.get_typed(session, "routing_weights", RoutingWeights)
    provider_config = config_service.get_typed(session, "providers", ProviderConfig)
    catalog = build_catalog(session)
    stats = _load_stats(session, operation, quality_tier)

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

        retry_amplification = setting.retry_amplification if setting is not None else 1.2
        stat = stats.get(name)
        success_rate = _success_rate(stat, provider_config)
        # Failures are not free: a provider that fails a third of the time
        # really costs about 1.5 attempts per success.
        candidate.effective_cost = int(
            capability.unit_cost_minor * retry_amplification / max(success_rate, 0.05)
        )

        candidate.quality_score = capability.quality_prior
        candidate.latency_score = _latency_score(stat, capability)
        candidate.cost_score = _cost_score(candidate.effective_cost)
        candidate.reliability_score = success_rate
        candidate.total_score = round(
            weights.quality * candidate.quality_score
            + weights.latency * candidate.latency_score
            + weights.cost * candidate.cost_score
            + weights.reliability * candidate.reliability_score,
            6,
        )
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

    # Deterministic ordering: score, then cheaper, then name. Two identical
    # requests must always route the same way.
    eligible.sort(key=lambda c: (-c.total_score, c.effective_cost, c.provider))
    winner = eligible[0]
    return RoutingDecision(
        selected=winner,
        candidates=candidates,
        reason=f"highest_score:{winner.total_score:.4f}",
        catalog=catalog,
    )


def _load_stats(session: Session, operation: str, quality_tier: str) -> dict[str, ProviderStat]:
    rows = session.scalars(
        select(ProviderStat).where(
            ProviderStat.operation == operation, ProviderStat.quality_tier == quality_tier
        )
    )
    return {row.provider: row for row in rows}


def _success_rate(stat: ProviderStat | None, config: ProviderConfig) -> float:
    """Falls back to a conservative prior until there is enough evidence.

    Without this, a provider with a single lucky success would outrank one with
    hundreds of reliable runs.
    """
    if stat is None or stat.attempts < config.minimum_samples_for_stats:
        return config.conservative_prior_success_rate
    return max(0.01, min(1.0, stat.successes / stat.attempts))


def _latency_score(stat: ProviderStat | None, capability: ProviderCapability) -> float:
    observed = (
        stat.total_latency_ms / stat.attempts
        if stat is not None and stat.attempts > 0
        else capability.typical_latency_ms
    )
    # 5s scores ~1.0, 60s scores ~0.08; a smooth curve avoids cliff effects at
    # any particular threshold.
    return round(min(1.0, 5_000 / max(observed, 1_000)), 6)


def _cost_score(effective_cost: int) -> float:
    return round(min(1.0, 5 / max(effective_cost, 1)), 6)


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
