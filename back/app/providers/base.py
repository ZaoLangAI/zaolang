"""Generation provider interface.

Both shipped providers are fakes. The interface is what real providers will
implement, so swapping one in requires no change to the worker or the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.enums import MediaGenerationKind, ProviderKind
from app.platform_config.schemas import MediaPricing

# Canonical resolution tiers a client can request (`VideoGenerationOptions
# .resolution`), independent of any one vendor's spelling. Add a synonym
# here — never a new hard-filter code path — when a differently-cased model
# gets deployed (e.g. a future `wan3.0-video` endpoint's capital-P
# `480P`/`720P`/`1080P`, already listed below even though nothing using that
# spelling is deployed yet); this table is the only place that needs to
# change. `768P` (MiniMax H3's own token) is deliberately a `720p` synonym,
# not its own tier, so H3 and the lowercase-`p` models (`doubao-seedance-2-5
# -260628`, `wan2.7-videoedit`) can actually compete for the same client
# request instead of being invisible to each other over a spelling
# difference — see `resolve_resolution_tier`.
RESOLUTION_TIER_MEMBERS: dict[str, frozenset[str]] = {
    "480p": frozenset({"480p", "480P"}),
    "720p": frozenset({"720p", "720P", "768P"}),
    "1080p": frozenset({"1080p", "1080P"}),
    "2K": frozenset({"2K"}),
}

# Lowest → highest. `adapt_resolution_tier` only walks *down* this list
# (then, as a last resort so a job does not die, the lowest supported
# tier). Never treat 1080p and 2K as synonyms.
STUDIO_RESOLUTION_TIERS: tuple[str, ...] = ("480p", "720p", "1080p", "2K")

ResolutionAdaptKind = Literal["exact", "downgrade", "upgrade"]


@dataclass(frozen=True, slots=True)
class AdaptedResolution:
    """What a specific candidate should actually render after adaptation.

    `studio_tier` is the client-facing token (`480p`/`720p`/`1080p`/`2K`);
    `vendor_literal` is that candidate's own spelling (`768P`, `1080p`, …).
    `kind` is `exact` when the requested tier is honoured, `downgrade` when
    a strictly lower supported tier was picked, and `upgrade` only when
    nothing at or below the request exists (the model's lowest tier).
    """

    studio_tier: str
    vendor_literal: str
    kind: ResolutionAdaptKind


def resolve_resolution_tier(tier: str | None, available: frozenset[str] | None) -> str | None:
    """The one literal resolution string a specific model should actually
    receive for a client-requested tier token.

    Returns `None` when `tier` is unset (a video remix omits `resolution`
    entirely so the router does not default-filter a cheaper edit model —
    the provider's own default applies downstream) or when `available` (a
    candidate's `ProviderCapability.resolutions`) has nothing belonging to
    that tier — the caller must treat that as ineligible, never silently
    substitute a different tier. An unrecognised tier falls back to treating
    itself as its own one-member synonym set, so a raw vendor literal passed
    straight through (e.g. by a test or an old checkpoint) still resolves
    exactly like today's plain equality check used to.
    """
    if not tier or available is None:
        return None
    members = RESOLUTION_TIER_MEMBERS.get(tier, frozenset({tier}))
    matches = sorted(available & members)
    return matches[0] if matches else None


def studio_tier_for_literal(literal: str | None) -> str | None:
    """The client-facing tier a vendor spelling belongs to, or `None`."""

    if not literal:
        return None
    for tier, members in RESOLUTION_TIER_MEMBERS.items():
        if literal == tier or literal in members:
            return tier
    return None


def studio_resolution_tiers(available: frozenset[str] | None) -> list[str] | None:
    """Client-facing tiers this candidate can honour. `None` = unrestricted."""

    if available is None:
        return None
    return [
        tier
        for tier in STUDIO_RESOLUTION_TIERS
        if resolve_resolution_tier(tier, available) is not None
    ]


def adapt_resolution_tier(
    requested: str | None, available: frozenset[str] | None
) -> AdaptedResolution | None:
    """Map a client's resolution *ceiling* onto one candidate's vocabulary.

    The requested value stays a user intent (highest acceptable tier), not
    a must-match. An omitted `requested` (video remix) returns `None` so
    the provider's own default applies — never invent a tier. An
    unrestricted candidate (`available is None`) passes the request
    through unchanged. Otherwise: exact tier if the candidate has it;
    else the highest *strictly lower* supported tier; else the candidate's
    lowest supported tier (`kind="upgrade"`) so the job still runs. A
    candidate whose `resolutions` map to no studio tier at all returns
    `None` — that is the only remaining hard-filter case.
    """

    if not requested:
        return None
    if available is None:
        return AdaptedResolution(studio_tier=requested, vendor_literal=requested, kind="exact")
    exact = resolve_resolution_tier(requested, available)
    if exact is not None:
        return AdaptedResolution(studio_tier=requested, vendor_literal=exact, kind="exact")
    try:
        req_idx = STUDIO_RESOLUTION_TIERS.index(requested)
    except ValueError:
        req_idx = None
    if req_idx is not None:
        for tier in reversed(STUDIO_RESOLUTION_TIERS[:req_idx]):
            literal = resolve_resolution_tier(tier, available)
            if literal is not None:
                return AdaptedResolution(studio_tier=tier, vendor_literal=literal, kind="downgrade")
    for tier in STUDIO_RESOLUTION_TIERS:
        literal = resolve_resolution_tier(tier, available)
        if literal is not None:
            return AdaptedResolution(studio_tier=tier, vendor_literal=literal, kind="upgrade")
    return None


@dataclass(slots=True)
class ProviderReference:
    """One already-authorised private asset passed to a media provider.

    ``media_type`` is deliberately the small platform enum value (``image`` or
    ``video``), not a user supplied MIME string. ``frame_type`` started as
    "populated only for MiniMax-style first/last-frame requests" and has
    since widened into a general reference-role tag: still ``"first_frame"``/
    ``"last_frame"`` for that case, but also ``"base_video"`` for the one
    source clip a MiniMax-H3 video-regeneration request carries (see
    ``app.providers.dmxapi_media``) — a reference with no ``frame_type`` at
    all is a generic reference (image/video/audio) rather than a positional
    frame or a regeneration source.
    """

    object_key: str
    media_type: str
    frame_type: str | None = None
    # Which platform `Asset` this came from — lets the prompt's reference
    # legend name the exact images the provider receives, in order. `None`
    # on checkpoints written before the field existed.
    asset_id: str | None = None


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
    # How many separate images one call should return (a scene variant
    # group). Only a capability with `max_outputs_per_call >= output_count`
    # is ever routed such a request (`router._request_constraint_failure`);
    # every other adapter can ignore it.
    output_count: int = 1

    def __post_init__(self) -> None:
        # JSON checkpoints turn nested dataclasses back into dictionaries.
        # Normalise them here so old and new in-flight tasks resume through the
        # exact same provider code without a data migration.
        self.references = [
            item if isinstance(item, ProviderReference) else ProviderReference(**item)
            for item in self.references
        ]


@dataclass(slots=True)
class GeneratedOutput:
    """One additional image a group-capable call returned, beyond the
    primary `GenerationResult.object_key`."""

    object_key: str
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None


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
    # A group call's images after the first (`GenerationRequest.output_count`
    # > 1), in the order the provider returned them. Empty for every
    # single-output call, so existing callers never see a difference.
    extra_outputs: list[GeneratedOutput] = field(default_factory=list)

    @property
    def delivered_outputs(self) -> int:
        return (1 if self.object_key else 0) + len(self.extra_outputs)


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
    # Which `app.domain.costs.service` billing shape `pricing` follows (see
    # `LlmProviderEndpoint.billing_profile`) — `None` for an endpoint priced
    # the default per-second/per-image/per-request way.
    billing_profile: str | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    aspect_ratios: frozenset[str] | None = None
    resolutions: frozenset[str] | None = None
    # What this model actually renders at when a request leaves `resolution`
    # unset — the same value the provider adapter itself falls back to when
    # building the upstream call (`NativeVideoModelProfile`/`VideoModelProfile
    # .default_resolution`). Costing must use this, not a fixed nominal
    # resolution, or a model whose real default nothing in the request names
    # (a `resolve_resolution_tier` call with `tier=None` always resolves to
    # `None`, whatever this model's own vocabulary is) prices every call at a
    # resolution it never actually rendered at.
    default_resolution: str | None = None
    reference_modes: frozenset[str] | None = None
    # Copied from `LlmProviderEndpoint.generation_kind`. Edit-class video
    # models are hard-filtered when the request has no video source.
    generation_kind: MediaGenerationKind = MediaGenerationKind.CREATE
    # `music_generation` only: which `extra.audio_style` value(s)
    # (`"music"`/`"sfx"`) this specific model actually produces — see
    # `app.providers.dmxapi_media.music_style_for_model`/`app.providers.
    # fal_media.music_style_for_model`. `None` for every other operation
    # (no hard filter) and for a `music_generation` model this table does
    # not yet recognise (same "unrestricted rather than mis-modelled"
    # stance `reference_modes`/`aspect_ratios` take elsewhere in this
    # class) — `_request_constraint_failure` only filters when this is set.
    music_styles: frozenset[str] | None = None
    # Whether this model takes a *video* among its multimodal references
    # (MiniMax H3 / Seedance 2.5 / wan3.0 "reference-to-video"). Only
    # consulted for a `reference_video_role="motion_guide"` request — a 白膜
    # blockout clip must reach a model that reads it as guidance, never one
    # that silently drops it or (an edit model) restyles it as the output.
    accepts_video_reference: bool = False
    # How many generic (non-frame) *image* references this model actually
    # receives, front-first — adapters truncate `references` from the front
    # (`keys[:N]`), so the first N are exactly what it sees. `None` = unknown,
    # which makes the reference legend stay silent rather than name an
    # image the model may never get (`prompt_builder.reference_legend`).
    max_image_references: int | None = None
    # Most separate images one call can return (`GenerationRequest.
    # output_count`): 1 for every model except a group-capable one
    # (Seedream's sequential image generation).
    max_outputs_per_call: int = 1
    # Takes an explicit camera pose (`extra.camera_pose`) instead of reading
    # the move from the prompt — today only fal's Qwen-Image-Edit-2511
    # multiple-angles LoRA (`fal_media.supports_camera_control`). The router
    # prefers these for a posed pass and keeps them away from any other
    # request (`router._request_constraint_failure`).
    camera_control: bool = False


def probe_image_size(payload: bytes) -> tuple[int | None, int | None]:
    """A just-generated image's pixel size, `(None, None)` when undecodable —
    never fails an otherwise-successful generation."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None


def probe_audio_duration_ms(payload: bytes, mime_type: str) -> int | None:
    """`ffprobe`'s real duration for a just-generated audio/music payload.

    Every audio/music provider (`_submit_audio`/`_submit_music` across
    `aihubmix_media.py`/`dmxapi_media.py`/`fal_media.py`) calls this right
    before returning its `GenerationResult`, so a TTS/BGM/SFX output's
    timeline length is known immediately instead of the editor guessing —
    unlike the dry-run stub (`workflows/nodes.py`'s hardcoded
    `duration_ms=1000`), a real provider call must report the real number.

    Imported lazily to avoid a cycle: `app.domain.editor.analysis` itself
    imports `app.providers.aihubmix_media` (for `media_client_base`/
    `media_request_path`), so this module cannot import it back at load
    time. Missing `ffprobe` degrades to `None`, same as `probe_bytes`
    itself for an upload — but unlike an upload, a probe failure here must
    never fail an otherwise-successful generation (same "swallow, don't
    fail the finished job" rule as an episode preview's frame extraction),
    so `probe_bytes`'s own `ValidationFailed` on a bad/undecodable payload
    is caught and downgraded to `None` too.
    """
    from app.domain.editor.analysis import probe_bytes
    from app.domain.errors import ValidationFailed

    try:
        _, _, duration_ms = probe_bytes(payload, mime_type)
    except ValidationFailed:
        return None
    return duration_ms
