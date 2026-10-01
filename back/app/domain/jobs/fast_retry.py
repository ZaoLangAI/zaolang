"""Skips a retry straight to `route_score` when its content is provably unchanged.

`POST /v1/generation-jobs/{id}/retry` (`app.api.v1.jobs.retry_job`) already
resubmits `original.request_json` verbatim — there is no way for a client to
change anything through that endpoint, so "input unchanged" always holds for
the job it creates. That new job still walks the *entire* graph from
`safety_check` by default, re-paying for a judgment call, a plan, and an
intent-router classification that already ran once and cannot have changed.

`build_seed` is the eligibility gate: it only fires when the *previous*
attempt actually reached a real provider and that provider genuinely failed
(the "根据之前的报错情况重新评估" case) — a safety rejection, a `no_candidate`/
`retries_exhausted` routing dead-end (no provider was ever called), or a
`QUALITY_REJECTED` output (the provider itself did nothing wrong) all still
walk the full graph, since skipping safety/planning there would either be
unsafe or simply wouldn't change anything. Character/scene/cover asset-kind
jobs (image or video) are also excluded for now — `execute_asset_planning`/
`execute_asset_output_advance` depend on per-pass state (`_current_character_view`
and friends) that only that node sets up; skipping it would corrupt which
view a produced asset gets tagged as. See `zaolang-generation-jobs` skill's
extension points for the fuller writeup.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.image_assets import prompt_builder
from app.models import GenerationJob, JobEvent, ProviderAttempt
from app.models.enums import (
    ImageAssetKind,
    JobEventType,
    Operation,
    ProviderAttemptStatus,
    VideoAssetKind,
)

# Mirrors `back/app/api/v1/jobs.py`'s own `VIDEO_OPERATIONS` — kept as a
# separate copy rather than an import to avoid a domain-module -> api-module
# dependency; the two operation lists are enum-derived and structurally
# guaranteed to agree.
_FAST_RETRY_OPERATIONS = frozenset(
    {
        Operation.TEXT_TO_IMAGE.value,
        Operation.IMAGE_TO_IMAGE.value,
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)

# The three codes `aihubmix_media.py`/`dmxapi_media.py` use to classify a
# genuine upstream failure (see the `zaolang-agent-gateway` providers
# reference on classifying poll errors, and `zaolang-generation-jobs` on fast
# retry).
# Deliberately excludes `MISSING_REFERENCE` (a user-input problem no provider
# switch fixes), `PROVIDER_TIMEOUT` (sandbox-only synchronous-poll timeout),
# and `QUALITY_REJECTED` (the provider produced something; quality rejected
# it) — none of those are "the provider we picked was the problem".
_REAL_PROVIDER_FAILURE_CODES = frozenset(
    {"PROVIDER_TEMPORARY_FAILURE", "PROVIDER_INVALID_RESPONSE", "PROVIDER_TASK_FAILED"}
)


@dataclass(slots=True)
class FastRetrySeed:
    """What `run_generation_pipeline` needs to start a retry at `route_score`.

    `prompt`/`negative_prompt` are the *already-resolved* values the failed
    attempt actually sent to the provider (recovered from its own
    `JobEvent`, not recomputed) — planning/asset-planning never ran again to
    produce them. `tried_providers` seeds `route_score`'s existing
    same-job exclusion set (`app.workflows.nodes.execute_route_score`) so the
    provider that just failed is hard-filtered out of this new job's
    candidates too, exactly the way a same-job provider retry already
    excludes it.
    """

    prompt: str
    negative_prompt: str | None
    tried_providers: set[str]


def build_seed(session: Session, retry_job: GenerationJob) -> FastRetrySeed | None:
    """Returns a seed when `retry_job` (a brand-new job) can skip to `route_score`.

    `None` means "walk the full graph as usual" — every check below is a
    reason to fall back safely rather than to error, since a custom/edited
    workflow template or a job predating some column is always a legitimate
    reason this can't apply.
    """
    if not retry_job.retry_of_job_id:
        return None
    if retry_job.operation not in _FAST_RETRY_OPERATIONS:
        return None
    if _has_asset_axis(retry_job.request_json or {}):
        return None

    original = session.get(GenerationJob, retry_job.retry_of_job_id)
    if original is None:
        return None
    if original.failure_code not in _REAL_PROVIDER_FAILURE_CODES:
        return None

    tried_providers = _failed_providers(session, original.id)
    if not tried_providers:
        return None

    resolved = _resolved_prompt(session, original.id)
    if resolved is None:
        return None
    prompt, negative_prompt = resolved

    return FastRetrySeed(
        prompt=prompt, negative_prompt=negative_prompt, tried_providers=tried_providers
    )


def _has_asset_axis(params: dict[str, object]) -> bool:
    """Same two-axis check as `app.workflows.nodes._asset_axis`, on raw params."""
    image_kind = params.get("asset_kind")
    if isinstance(image_kind, str) and image_kind != ImageAssetKind.GENERAL.value:
        return True
    video_kind = params.get("video_asset_kind")
    return isinstance(video_kind, str) and video_kind != VideoAssetKind.GENERAL.value


def _failed_providers(session: Session, job_id: str) -> set[str]:
    rows = session.scalars(
        select(ProviderAttempt.provider).where(
            ProviderAttempt.job_id == job_id,
            ProviderAttempt.status == ProviderAttemptStatus.FAILED,
        )
    )
    return {provider for provider in rows if provider}


def _resolved_prompt(session: Session, job_id: str) -> tuple[str, str | None] | None:
    """The last `prompt`/`negative_prompt` the failed job actually sent.

    `execute_provider_generate` (`app.workflows.nodes`) writes exactly this
    pair into a `JobEventType.GENERATING` event's payload right before every
    provider call, succeeding or not — reading the most recent one back is
    cheaper and more faithful than recomputing it (which would require
    re-running `planning` and cannot be guaranteed to produce byte-identical
    output from an LLM anyway).
    """
    event = session.scalar(
        select(JobEvent)
        .where(JobEvent.job_id == job_id, JobEvent.event_type == JobEventType.GENERATING.value)
        .order_by(JobEvent.sequence.desc())
        .limit(1)
    )
    if event is None:
        return None
    payload = event.payload_json or {}
    # `base_prompt` is the prompt before the reference legend was prefixed;
    # the retry's own `provider_generate` adds a fresh one, so seeding with
    # the legend would send it twice.
    prompt = payload.get("base_prompt") or payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return None
    prompt = prompt_builder.strip_reference_legend(prompt)
    negative_prompt = payload.get("negative_prompt")
    return prompt, negative_prompt if isinstance(negative_prompt, str) else None
