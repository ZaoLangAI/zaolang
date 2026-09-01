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

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import intent_router
from app.domain.costs import service as costs_service
from app.models import ProviderStat
from app.providers.base import ProviderCapability
from app.providers.media_endpoints import dynamic_capabilities

CONSERVATIVE_PRIOR_SUCCESS_RATE = 0.8
# How many "virtual" trials the prior above is worth when blending it with
# real attempts — see `_success_rate`. Not a hard sample-count threshold.
PRIOR_PSEUDO_SAMPLES = 8
RETRY_COST_AMPLIFICATION = 1.2


def build_catalog(session: Session) -> dict[str, ProviderCapability]:
    """Every enabled database-configured media route.

    Built fresh per call — like every other config-driven lookup in this
    codebase — so an operator adding an endpoint at `/admin/models` takes
    effect on the very next job, not after a restart.
    """
    return dynamic_capabilities(session)


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
    # A representative call's price inflated by how often this provider has to
    # be retried, in micro-USD.
    effective_cost_micro_usd: int = 0
    # This request's own price, from its duration/resolution/reference count.
    estimated_cost_micro_usd: int = 0
    # Both figures above rest on a built-in prior rather than a configured
    # price. Without this flag an unpriced provider reads as a cheap one.
    cost_is_estimated: bool = False

    def to_trace(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class RoutingDecision:
    selected: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    catalog: dict[str, ProviderCapability] = field(default_factory=dict)
    # The `intent_router` agent call that made (or failed to make) this
    # selection, so `route_score`'s node can be tagged as the node that ran
    # it — `None` only when there were no eligible candidates to show it.
    agent_run_id: str | None = None

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
    selector_agent_id: str | None = None,
    request_params: Mapping[str, Any] | None = None,
    cost_bias: float | None = None,
) -> RoutingDecision:
    """Filters the catalogue down to what can actually serve this job, then
    lets the routing agent pick.

    `cost_bias` is `intent_router.classify()`'s request-level cost signal
    (`None` when no `classify()` ran ahead of this call, e.g. a direct test).
    Forwarded to `select_provider` as context only.
    """
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
        constraint_failure = _request_constraint_failure(capability, request_params or {})
        if constraint_failure is not None:
            candidate.eligible = False
            candidate.filter_reason = constraint_failure
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

        stat = stats.get(name)
        success_rate = _success_rate(stat)
        # Failures are not free: a provider that fails a third of the time
        # really costs about 1.5 attempts per success. Still shown to the
        # LLM (and the replay console) even though nothing here ranks by it
        # any more.
        candidate.effective_cost_micro_usd = int(
            capability.unit_cost_micro_usd * RETRY_COST_AMPLIFICATION / max(success_rate, 0.05)
        )
        candidate.estimated_cost_micro_usd = costs_service.estimate_media_request_cost_micro_usd(
            capability.pricing,
            capability=operation,
            params=request_params or {},
            billing_profile=capability.billing_profile,
            default_resolution=capability.default_resolution,
        )
        candidate.cost_is_estimated = capability.cost_is_estimated
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
        cost_bias=cost_bias,
        job_id=job_id,
        user_id=user_id,
        agent_id=selector_agent_id,
    )
    selected_name = outcome.data.get("selected_provider")
    winner = next((c for c in eligible if c.provider == selected_name), None)
    if outcome.degraded or winner is None:
        return RoutingDecision(
            selected=None,
            candidates=candidates,
            reason="llm_selection_unavailable",
            catalog=catalog,
            agent_run_id=outcome.agent_run_id,
        )

    rationale = outcome.data.get("rationale")
    reason = (
        f"llm_selected:{rationale}" if isinstance(rationale, str) and rationale else "llm_selected"
    )
    return RoutingDecision(
        selected=winner,
        candidates=candidates,
        reason=reason,
        catalog=catalog,
        agent_run_id=outcome.agent_run_id,
    )


def _request_constraint_failure(
    capability: ProviderCapability, params: Mapping[str, Any]
) -> str | None:
    """Hard-filter a provider that physically cannot honour the request."""

    duration = int(params.get("duration_seconds") or 0)
    if capability.min_duration_seconds is not None and duration < capability.min_duration_seconds:
        return "duration_below_provider_minimum"
    if capability.max_duration_seconds is not None and duration > capability.max_duration_seconds:
        return "duration_above_provider_maximum"
    aspect_ratio = str(params.get("aspect_ratio") or "16:9")
    if capability.aspect_ratios is not None and aspect_ratio not in capability.aspect_ratios:
        return "aspect_ratio_not_supported"
    video_options = params.get("video_options")
    if isinstance(video_options, Mapping):
        raw_resolution = video_options.get("resolution")
        reference_mode = str(video_options.get("reference_mode") or "input_references")
        if (
            raw_resolution
            and capability.resolutions is not None
            and str(raw_resolution) not in capability.resolutions
        ):
            return "resolution_not_supported"
        if (
            capability.reference_modes is not None
            and reference_mode not in capability.reference_modes
        ):
            return "reference_mode_not_supported"
    return None


def _candidate_payload(candidate: Candidate, capability: ProviderCapability) -> dict[str, Any]:
    """What the selecting agent is shown about one candidate.

    Context, not a ranking: nothing here is combined into a score. The two
    cost figures answer different questions — `effective_cost_micro_usd`
    compares providers in general, `estimated_cost_micro_usd` prices *this*
    request — and `cost_is_estimated` says whether either can be trusted.

    `model` is the real model/workflow name behind this candidate
    (`capability.model_or_workflow`) — the only way the agent can actually
    tell candidates apart by identity, since `provider` is an opaque catalog
    key (`f"{endpoint_id}:{tag}"`), not a model name. `quality_prior` stays a
    flat system default (see `media_endpoints._QUALITY_PRIOR`); it is not a
    real per-model quality score, so quality judgment is left to the agent's
    own knowledge of `model` — see `SELECT_PROVIDER_SYSTEM_PROMPT`.
    """
    return {
        "provider": candidate.provider,
        "model": capability.model_or_workflow,
        "kind": capability.kind.value,
        "quality_prior": capability.quality_prior,
        "success_rate": candidate.success_rate,
        "avg_latency_ms": candidate.avg_latency_ms,
        "effective_cost_micro_usd": candidate.effective_cost_micro_usd,
        "estimated_cost_micro_usd": candidate.estimated_cost_micro_usd,
        "cost_is_estimated": candidate.cost_is_estimated,
    }


def _load_stats(session: Session, operation: str, quality_tier: str) -> dict[str, ProviderStat]:
    rows = session.scalars(
        select(ProviderStat).where(
            ProviderStat.operation == operation, ProviderStat.quality_tier == quality_tier
        )
    )
    return {row.provider: row for row in rows}


def _success_rate(stat: ProviderStat | None) -> float:
    """Blends the observed success rate with a conservative prior via
    additive (Beta) smoothing, rather than switching sharply at a fixed
    sample-count threshold.

    With `attempts=0` this returns the prior untouched. As real attempts
    accumulate, the prior's influence fades in proportion to
    `PRIOR_PSEUDO_SAMPLES` — a handful of live failures pulls the number down
    well before a hard cutoff would have kicked in, instead of a provider
    that is failing right now still reading as a reliable 0.8 until it has
    accumulated dozens of samples. A single lucky success is, symmetrically,
    still nowhere near 1.0.
    """
    if stat is None or stat.attempts == 0:
        return CONSERVATIVE_PRIOR_SUCCESS_RATE
    prior_successes = CONSERVATIVE_PRIOR_SUCCESS_RATE * PRIOR_PSEUDO_SAMPLES
    blended = (stat.successes + prior_successes) / (stat.attempts + PRIOR_PSEUDO_SAMPLES)
    return max(0.01, min(1.0, blended))


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
    cost_micro_usd: int = 0,
) -> None:
    """Feeds real outcomes back into the statistics the router reads.

    `cost_minor` is what the provider adapter reported; `cost_micro_usd` is
    the same attempt priced against the endpoint's configured rate. They are
    accumulated separately because the first is whole cents and rounds a
    sub-cent call away entirely.
    """
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
    stat.total_cost_micro_usd += cost_micro_usd
    session.flush()
