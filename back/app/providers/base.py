"""Generation provider interface.

Both shipped providers are fakes. The interface is what real providers will
implement, so swapping one in requires no change to the worker or the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import ProviderKind
from app.platform_config.schemas import MediaPricing


@dataclass(slots=True)
class ProviderReference:
    """One already-authorised private asset passed to a media provider.

    ``media_type`` is deliberately the small platform enum value (``image`` or
    ``video``), not a user supplied MIME string.  ``frame_type`` is populated
    only for MiniMax-style first/last-frame requests.
    """

    object_key: str
    media_type: str
    frame_type: str | None = None


@dataclass(slots=True)
class GenerationRequest:
    job_id: str
    operation: str
    quality_tier: str
    prompt: str
    negative_prompt: str | None = None
    seed: int | None = None
    aspect_ratio: str = "16:9"
    duration_seconds: int = 0
    # Video only. `None` means "let the provider profile's own default
    # apply" — never send a bare literal here for a provider that has no
    # concept of resolution (e.g. image/audio).
    resolution: str | None = None
    references: list[ProviderReference] = field(default_factory=list)
    # Compatibility for checkpoints created before typed references existed.
    # They were image-only in the old UI, so the H3 adapter may safely migrate
    # them to ``ProviderReference(media_type="image")`` at call time.
    reference_object_keys: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    # Which `route_score` pass this is within the job (see `nodes.py::
    # execute_route_score`) — monotonically increasing and never reused
    # across the whole job, including across a multi-view `CHARACTER` job's
    # loop-back through `asset_planning`. A provider must fold this into its
    # output `object_key` (default 1 is still fine for every job that never
    # loops): reusing `generated/{job_id}/output.png` verbatim for a second
    # view collides with the first view's already-registered `Asset` row on
    # `uq_assets_object_key`, since both views share the same `job_id`.
    attempt_number: int = 1

    def __post_init__(self) -> None:
        # JSON checkpoints turn nested dataclasses back into dictionaries.
        # Normalise them here so old and new in-flight tasks resume through the
        # exact same provider code without a data migration.
        self.references = [
            item if isinstance(item, ProviderReference) else ProviderReference(**item)
            for item in self.references
        ]


@dataclass(slots=True)
class GenerationResult:
    succeeded: bool
    object_key: str | None = None
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    cost_minor: int = 0
    latency_ms: int = 0
    external_task_id: str | None = None
    failure_code: str | None = None
    # The upstream accepted the work and is still running it. Neither a
    # success nor a failure: the workflow suspends on a checkpoint and
    # `poll()` decides which it becomes. `external_task_id` is mandatory when
    # this is set — it is the only handle left to the work in flight.
    pending: bool = False
    # `video_analysis`'s own output shape: a structured text breakdown
    # instead of a media asset. Mutually exclusive with `object_key` — a
    # provider sets exactly one of the two depending on whether its
    # capability produces media or text.
    output_json: dict[str, Any] | None = None
    # Redacted before it reaches ProviderAttempt: no keys, no signed URLs.
    metadata: dict[str, Any] = field(default_factory=dict)


class GenerationProvider(ABC):
    name: str
    kind: str

    @abstractmethod
    def submit(self, request: GenerationRequest) -> GenerationResult:
        """Starts one generation attempt.

        Either returns a settled result (the synchronous case) or one with
        `pending=True` and an `external_task_id`, meaning the upstream is
        still working and `poll()` will decide the outcome later. An
        implementation must never block a worker waiting for a slow upstream:
        a render that takes minutes belongs in the pending path so the worker
        is free and the user sees progress in the meantime.
        """

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """Checks a pending task once, without blocking.

        `request` is the original one, replayed from the suspended workflow's
        checkpoint, so an implementation can work out where the artifact
        belongs and how long it should be without keeping state of its own.

        Only ever called for a result `submit()` marked pending, which a
        synchronous provider never returns — hence the default that reports a
        failure instead of raising: a scheduler tick must not crash because
        one row points at a provider that has since stopped supporting async
        work.
        """
        return GenerationResult(
            succeeded=False,
            failure_code="PROVIDER_POLL_UNSUPPORTED",
            external_task_id=external_task_id,
            metadata={"provider": self.name},
        )

    def cancel(self, external_task_id: str) -> bool:
        """Best-effort cancellation. Returning False is acceptable: the job may
        still complete and bill us, and settlement follows the real outcome."""
        return False


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """One routable capability: what `app/agents/router.py` scores and picks
    between. Lives here rather than in `router.py` so provider-directory
    modules (e.g. one building capabilities from a database endpoint) can
    construct these without importing the router — the router imports this
    module, never the reverse."""

    name: str
    kind: ProviderKind
    operations: frozenset[str]
    tiers: frozenset[str]
    # 0-1 baseline used before enough real samples exist.
    quality_prior: float
    typical_latency_ms: int
    # What one representative call costs us, in micro-USD (1e-6 USD). Micro
    # rather than minor units because a $0.00286 image is 0 cents.
    unit_cost_micro_usd: int
    model_or_workflow: str
    # Deferred so building the catalog never constructs a provider (and
    # therefore never opens a client/connection) for a route that ends up
    # not winning.
    provider_factory: Callable[[], GenerationProvider]
    # True when `unit_cost_micro_usd` came from a built-in prior instead of a
    # price the operator configured. Shown to the selecting agent so an
    # unpriced endpoint does not read as a cheap one.
    cost_is_estimated: bool = False
    # The endpoint's configured list prices, for costing a concrete request.
    # `None` when the route has no pricing block at all.
    pricing: MediaPricing | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    aspect_ratios: frozenset[str] | None = None
    resolutions: frozenset[str] | None = None
    reference_modes: frozenset[str] | None = None
