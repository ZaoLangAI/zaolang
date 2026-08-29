"""Typed schemas for every runtime-configurable key.

Config is validated on write, not on read. An operator who submits a bad
routing weight gets a 422 at edit time; the workers never have to defend
against a malformed value.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Operation, QualityTier

logger = logging.getLogger(__name__)

# The longest clip a generation request may ask for. Config that promises more
# than this would be unreachable, so every duration setting is capped by it.
MAX_GENERATION_DURATION_SECONDS = 30

# Added to a reasoning model's requested budget in `LlmProviderEndpoint
# .output_budget` — enough headroom for a chain-of-thought pass without
# handing the call the endpoint's *entire* declared ceiling on the first
# attempt (which used to be this method's unconditional behaviour): a call
# that spends this margin thinking and still hasn't produced a visible
# answer gets truncated and, for a streaming caller that cares, retried once
# with a doubled budget (see `LlmProviderEndpoint.expand_output_budget`)
# rather than being left to think for however long the full ceiling allows.
REASONING_THINKING_MARGIN_TOKENS = 4096


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PricingConfig(ConfigSection):
    """Credit price per operation and tier, plus the video surcharge."""

    tier_pricing: dict[str, dict[str, int]]
    video_base_seconds: int = Field(default=4, ge=0, le=60)
    video_per_second_surcharge: dict[str, int]

    @model_validator(mode="after")
    def _tiers_are_monotonic(self) -> PricingConfig:
        expected_operations = {operation.value for operation in Operation}
        actual_operations = set(self.tier_pricing)
        if actual_operations != expected_operations:
            missing_operations = sorted(expected_operations - actual_operations)
            extra_operations = sorted(actual_operations - expected_operations)
            raise ValueError(
                f"定价矩阵必须覆盖全部操作；缺少 {missing_operations}，未知 {extra_operations}。"
            )
        for operation, tiers in self.tier_pricing.items():
            missing = {t.value for t in QualityTier} - set(tiers)
            if missing:
                raise ValueError(f"{operation} 缺少档位定价: {sorted(missing)}")
            if not (
                tiers[QualityTier.PREVIEW]
                < tiers[QualityTier.STANDARD]
                < tiers[QualityTier.CINEMATIC]
            ):
                raise ValueError(f"{operation} 的档位价格必须随质量递增。")
            if any(price <= 0 for price in tiers.values()):
                raise ValueError(f"{operation} 的定价必须为正数。")
        return self

    @model_validator(mode="after")
    def _surcharge_covers_every_tier(self) -> PricingConfig:
        """A missing tier here would price a long video at the short price."""
        missing = {t.value for t in QualityTier} - set(self.video_per_second_surcharge)
        if missing:
            raise ValueError(f"缺少视频每秒加价档位: {sorted(missing)}")
        if any(price < 0 for price in self.video_per_second_surcharge.values()):
            raise ValueError("视频每秒加价不能为负。")
        return self


class AgentModelBinding(ConfigSection):
    model: str
    max_tokens: int = Field(default=1024, ge=64, le=32_768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Reasoning models spend part of the budget on hidden thinking, so their
    # ceiling has to be raised well above the visible output length.
    reasoning_model: bool = False


class RoyaltyConfig(ConfigSection):
    enabled: bool = True
    first_level_rate_bps: int = Field(default=1000, ge=0, le=5000)
    decay_bps: int = Field(default=5000, ge=0, le=10_000)
    max_levels: int = Field(default=3, ge=1, le=10)
    min_payout: int = Field(default=1, ge=1)
    total_cap_bps: int = Field(default=2000, ge=0, le=10_000)

    @model_validator(mode="after")
    def _cap_covers_first_level(self) -> RoyaltyConfig:
        if self.enabled and self.total_cap_bps < self.first_level_rate_bps:
            raise ValueError("总上限不能低于第一层分成比例。")
        return self


class ShortformProfile(ConfigSection):
    """One short-video delivery spec.

    The platform validates against these numbers rather than the destination
    app's own rules, so a spec change is an operator edit instead of a deploy.
    """

    aspect_ratio: str = Field(default="9:16", pattern=r"^\d{1,2}:\d{1,2}$")
    width: int = Field(default=1080, ge=240, le=7680)
    height: int = Field(default=1920, ge=240, le=7680)
    min_duration_seconds: int = Field(default=5, ge=1, le=MAX_GENERATION_DURATION_SECONDS)
    # Capped by `GenerationParams.duration_seconds`, which refuses anything longer.
    max_duration_seconds: int = Field(default=30, ge=1, le=MAX_GENERATION_DURATION_SECONDS)
    max_title_length: int = Field(default=55, ge=1, le=200)
    max_hashtags: int = Field(default=5, ge=0, le=30)
    # Overlay reserved by the destination app's own UI, as a percentage of the
    # frame. Text placed inside it is at risk of being covered.
    safe_area_top_pct: int = Field(default=12, ge=0, le=100)
    safe_area_bottom_pct: int = Field(default=22, ge=0, le=100)
    safe_area_right_pct: int = Field(default=18, ge=0, le=100)
    require_ai_disclosure: bool = True

    @model_validator(mode="after")
    def _durations_and_areas_are_coherent(self) -> ShortformProfile:
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("最短时长不能大于最长时长。")
        if self.safe_area_top_pct + self.safe_area_bottom_pct >= 100:
            raise ValueError("上下安全区之和必须小于 100%。")
        return self


class ShortformConfig(ConfigSection):
    profiles: dict[str, ShortformProfile]
    default_profile: str = "douyin_vertical"
    # Finer-grained kill switches underneath `FeatureFlags.shortform_studio`:
    # the studio surface can stay open while either of these ships off
    # instantly without a deploy.
    enable_clarifying_questions: bool = True
    enable_preview_picker: bool = True
    # How many `QualityTier.PREVIEW` drafts the studio submits before the
    # user picks one to promote. Capped at 3 so a fat-fingered admin edit
    # cannot silently multiply everyone's preview cost.
    preview_candidate_count: int = Field(default=3, ge=2, le=3)

    @model_validator(mode="after")
    def _default_profile_exists(self) -> ShortformConfig:
        if not self.profiles:
            raise ValueError("至少需要一个短视频规格。")
        if self.default_profile not in self.profiles:
            raise ValueError(f"默认规格 {self.default_profile} 不在规格目录中。")
        return self


class MarketplaceConfig(ConfigSection):
    """Paid unlock of remixable works and published skills.

    The fee is burned (not booked to a platform account): buyer pays `price`,
    seller receives `price - fee`, so mutual farming is lossy.
    """

    platform_fee_bps: int = Field(default=1000, ge=0, le=10_000)
    max_access_credits: int = Field(default=10_000, ge=1)


class FeatureFlags(ConfigSection):
    video_generation: bool = True
    public_registration: bool = True
    shortform_studio: bool = True
    drama_studio_enabled: bool = False
    web_editor_enabled: bool = False
    variant_export_enabled: bool = False
    editor_ai_enabled: bool = False
    editor_mcp_enabled: bool = False
    marketplace_enabled: bool = True
    # Independent of `drama_studio_enabled`: script writing can ship before
    # the full episode/cut editor does, and gating it on the bigger flag
    # would block that staged rollout.
    script_studio_enabled: bool = False
    # Gates the "视频解析" creation tool end to end: the `/create` page's
    # tool card, and `POST /v1/generation-jobs` for `operation=video_analysis`
    # (same "off means 404/hidden" staged-rollout shape as `script_studio_enabled`).
    video_analysis_enabled: bool = False
    # Rollout percentage keyed by flag name, evaluated per user id hash.
    rollout_percentages: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _percentages_in_range(self) -> FeatureFlags:
        allowed = {
            "video_generation",
            "shortform_studio",
            "drama_studio_enabled",
            "web_editor_enabled",
            "variant_export_enabled",
            "editor_ai_enabled",
            "editor_mcp_enabled",
            "marketplace_enabled",
            "script_studio_enabled",
            "video_analysis_enabled",
        }
        for name, pct in self.rollout_percentages.items():
            if name not in allowed:
                raise ValueError(f"{name} 不支持灰度发布。")
            if not 0 <= pct <= 100:
                raise ValueError(f"灰度比例 {name}={pct} 必须在 0-100 之间。")
        return self


class KeywordModerationConfig(ConfigSection):
    blocked_keywords: list[str] = Field(default_factory=list)

    @field_validator("blocked_keywords", mode="before")
    @classmethod
    def _normalise_keywords(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return value
        normalised: list[str] = []
        seen: set[str] = set()
        for item in value:
            keyword = str(item).strip().casefold()
            if keyword and keyword not in seen:
                seen.add(keyword)
                normalised.append(keyword)
        return normalised


class ContentModerationConfig(KeywordModerationConfig):
    pass


class LearningModerationConfig(KeywordModerationConfig):
    pass


class SkillModerationConfig(KeywordModerationConfig):
    pass


# The six media generation capabilities a provider endpoint may declare,
# alongside the one general (text + vision) pool. Equal to every `Operation`
# value: each media generation job maps 1:1 onto one capability tag.
MEDIA_CAPABILITIES: list[str] = [op.value for op in Operation]

# The modality axes an operator picks from instead of naming a capability tag
# directly. Every `Operation` maps onto exactly one (input, output) pair below,
# so declaring modalities is equivalent to declaring capabilities — just
# phrased in terms a non-engineer can reason about ("this model reads images
# and writes video") rather than the internal tag vocabulary. `audio` is a
# valid *input* modality (e.g. voice-driven lip-sync video) even though no
# `Operation` pairs it with an output yet — declaring it alongside a modality
# that does derive a capability is harmless, it just contributes nothing on
# its own; see `_media_model_and_modalities_are_coherent` below.
MEDIA_INPUT_MODALITIES: list[str] = ["text", "image", "video", "audio"]
# `text` joined the output side alongside image/video/audio for
# `video_analysis` — the first capability that reads media and writes a
# structured text breakdown instead of generating more media.
MEDIA_OUTPUT_MODALITIES: list[str] = ["image", "video", "audio", "text"]

# `kind="general"` endpoints declare input types from this smaller set —
# `"text"` is always present (a chat endpoint always reads text), `"image"`
# is a declarative label only, `"video"` additionally makes the endpoint a
# `video_analysis` candidate. No `"audio"`: nothing consumes it for general
# endpoints yet. Ordered for stable display/round-tripping.
GENERAL_INPUT_MODALITIES: list[str] = ["text", "image", "video"]

# One (input modality, output modality) pair per `Operation` — the new
# capability-selection axis. There is no per-capability model any more: an
# endpoint declares one model plus which modalities it supports, and every
# `Operation` whose pair is fully covered becomes a servable capability.
_CAPABILITY_MODALITY_MAP: dict[Operation, tuple[str, str]] = {
    Operation.TEXT_TO_IMAGE: ("text", "image"),
    Operation.IMAGE_TO_IMAGE: ("image", "image"),
    Operation.TEXT_TO_VIDEO: ("text", "video"),
    Operation.IMAGE_TO_VIDEO: ("image", "video"),
    Operation.VIDEO_TO_VIDEO: ("video", "video"),
    Operation.AUDIO_GENERATION: ("text", "audio"),
    Operation.VIDEO_ANALYSIS: ("video", "text"),
}


def capabilities_for_modalities(
    input_modalities: Iterable[str], output_modalities: Iterable[str]
) -> set[str]:
    """Derives which `MEDIA_CAPABILITIES` tags a modality selection covers.

    Pure and stateless on purpose: both the admin API and the router-facing
    `media_endpoints.py` call this instead of storing the result, so the two
    can never drift apart.
    """
    inputs = set(input_modalities)
    outputs = set(output_modalities)
    return {
        operation.value
        for operation, (in_modality, out_modality) in _CAPABILITY_MODALITY_MAP.items()
        if in_modality in inputs and out_modality in outputs
    }


# HTTP contract names shown in the admin dropdown — not vendor names.
# AiHubMix's image/audio paths are OpenAI-compatible, so they display as OpenAI.
MediaProtocol = Literal["openai", "minimax", "comfyui", "google", "dashscope", "ark", "kling"]
MEDIA_PROTOCOLS: tuple[MediaProtocol, ...] = (
    "openai",
    "minimax",
    "comfyui",
    "google",
    "dashscope",
    "ark",
    "kling",
)
IMPLEMENTED_MEDIA_PROTOCOLS: frozenset[str] = frozenset({"openai", "minimax", "dashscope"})
# Video joined this set once the OpenAI Videos API track (`/v1/videos`
# create/retrieve/download_content`) landed in `AiHubMixMediaProvider` — not
# every model exposed on this protocol accepts a reference (`wan2.7-
# videoedit`'s OpenAI-shaped endpoint schema has no `input_reference`
# field), so `image_to_video`/`video_to_video` are declared here as "this
# protocol *can* carry them for a model that supports it", not a promise
# every openai-protocol video endpoint can edit.
_OPENAI_CAPABILITIES = frozenset(
    {
        Operation.TEXT_TO_IMAGE.value,
        Operation.IMAGE_TO_IMAGE.value,
        Operation.AUDIO_GENERATION.value,
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)
_MINIMAX_CAPABILITIES = frozenset(
    {
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)
_COMFYUI_CAPABILITIES = (_OPENAI_CAPABILITIES | _MINIMAX_CAPABILITIES) - {
    Operation.AUDIO_GENERATION.value
}
# DashScope (Alibaba) is the first implemented protocol whose only capability
# is `video_analysis` — Qwen-VL's OpenAI-compatible mode accepts a `video_url`
# content part and answers in plain text (see `AiHubMixMediaProvider`'s
# `_submit_video_analysis`). Scoped to this one capability only; don't widen
# it to image/video generation without a real endpoint that does that too.
_DASHSCOPE_CAPABILITIES = frozenset({Operation.VIDEO_ANALYSIS.value})
PROTOCOL_CAPABILITIES: dict[str, frozenset[str]] = {
    "openai": _OPENAI_CAPABILITIES,
    "minimax": _MINIMAX_CAPABILITIES,
    "comfyui": _COMFYUI_CAPABILITIES,
    "google": frozenset(),
    "dashscope": _DASHSCOPE_CAPABILITIES,
    "ark": frozenset(),
    "kling": frozenset(),
}


def infer_media_protocol(capabilities: Iterable[str]) -> MediaProtocol:
    """Guess the contract for a pre-protocol media endpoint.

    Video-only → MiniMax (the only implemented video-generation path).
    `video_analysis`-only → DashScope (the only implemented video-in/text-out
    path — an endpoint predating this capability could never have declared
    it, so this branch only ever fires for a freshly-created endpoint).
    Anything else, including mixed image+video leftovers, → OpenAI so the
    after-validator can reject the mismatch instead of silently picking a
    vendor.
    """
    caps = set(capabilities)
    if caps and caps <= _MINIMAX_CAPABILITIES:
        return "minimax"
    if caps and caps <= _DASHSCOPE_CAPABILITIES:
        return "dashscope"
    return "openai"


# --------------------------------------------------------------------------
# Provider list prices
# --------------------------------------------------------------------------
#
# What we pay a vendor, in **micro-USD** (1e-6 USD) integers. Distinct from
# `PricingConfig` above, which is what a *user* pays us in credits — these two
# never convert into one another.
#
# Micro-USD because vendor list prices go well below a cent: $0.00286 per image
# is 2_860, and rounding it into `cost_minor` would make it free. Every price a
# vendor publishes today lands on an exact integer here, so nothing is lost:
#
#   $0.060 / M tokens     ->      60_000 per million
#   $0.220 / M tokens     ->     220_000 per million
#   $0.00286 / image      ->       2_860
#   $0.02535 / image      ->      25_350
#   $0.141 / 10K chars    ->     141_000 per 10K
#   $0.12397 / second     ->     123_970
#   $0.0282 / image       ->      28_200
#
# Zero means "not declared" rather than "free": the router treats an unpriced
# endpoint as unknown-cost and falls back to a prior, and cost statistics skip
# it rather than reporting a spend of nothing.

MICRO_USD_PER_USD = 1_000_000
# Guards a fat-fingered decimal point: $1000 for one unit is not a real price.
_MAX_UNIT_PRICE_MICRO_USD = 1_000 * MICRO_USD_PER_USD
# Vendors quote video by output resolution. `2K` is the only resolution a job
# can request today (`VideoGenerationOptions`); `768P` is priceable ahead of
# the provider adapter supporting it, which is why this list is wider.
VIDEO_RESOLUTIONS: tuple[str, ...] = ("2K", "768P")

_MicroUsd = Field(default=0, ge=0, le=_MAX_UNIT_PRICE_MICRO_USD)


def _validated_resolution_prices(prices: dict[str, int]) -> dict[str, int]:
    unknown = sorted(set(prices) - set(VIDEO_RESOLUTIONS))
    if unknown:
        raise ValueError(f"不支持的视频分辨率: {unknown}")
    for resolution, price in prices.items():
        if price < 0 or price > _MAX_UNIT_PRICE_MICRO_USD:
            raise ValueError(f"分辨率 {resolution} 的单价超出允许范围。")
    return prices


class TokenPricing(ConfigSection):
    """Text-model list price, quoted per million tokens like every vendor."""

    input_per_million_micro_usd: int = _MicroUsd
    output_per_million_micro_usd: int = _MicroUsd

    @property
    def is_declared(self) -> bool:
        return bool(self.input_per_million_micro_usd or self.output_per_million_micro_usd)


class ImagePricing(ConfigSection):
    """Charged per image on both sides: references sent in are not free."""

    input_per_image_micro_usd: int = _MicroUsd
    generation_per_image_micro_usd: int = _MicroUsd

    @property
    def is_declared(self) -> bool:
        return bool(self.input_per_image_micro_usd or self.generation_per_image_micro_usd)


class AudioPricing(ConfigSection):
    """Speech synthesis is billed by input text length, not by output duration."""

    per_10k_characters_micro_usd: int = _MicroUsd

    @property
    def is_declared(self) -> bool:
        return bool(self.per_10k_characters_micro_usd)


class VideoPricing(ConfigSection):
    """Per-second, per-resolution, plus a per-image allowance for references.

    Generated output and supplied input material are priced separately even
    when a vendor happens to charge the same for both — one of them changing
    later must not silently move the other.
    """

    generation_per_second_micro_usd: dict[str, int] = Field(default_factory=dict)
    input_material_per_second_micro_usd: dict[str, int] = Field(default_factory=dict)
    # The first N reference images come with the request; extras are billed.
    reference_image_free_count: int = Field(default=5, ge=0, le=100)
    extra_reference_image_micro_usd: int = _MicroUsd

    @field_validator("generation_per_second_micro_usd", "input_material_per_second_micro_usd")
    @classmethod
    def _known_resolutions(cls, value: dict[str, int]) -> dict[str, int]:
        return _validated_resolution_prices(value)

    @property
    def is_declared(self) -> bool:
        return bool(
            self.generation_per_second_micro_usd
            or self.input_material_per_second_micro_usd
            or self.extra_reference_image_micro_usd
        )


class VideoAnalysisPricing(ConfigSection):
    """Billed per request, unlike generation pricing's per-second/per-image
    shape — a video-understanding call has one fixed cost regardless of how
    long the source clip is (within the 3-minute cap the C-end enforces),
    since the vendor charges per call/per-token on the response, not per
    second of input."""

    per_request_micro_usd: int = _MicroUsd

    @property
    def is_declared(self) -> bool:
        return bool(self.per_request_micro_usd)


class MediaPricing(ConfigSection):
    """The price sections a media endpoint declares.

    Each is optional because an endpoint only pays for what it can produce —
    the endpoint validator drops sections its capabilities do not cover, so an
    audio-only provider cannot carry a stale video price into a cost report.
    """

    image: ImagePricing | None = None
    audio: AudioPricing | None = None
    video: VideoPricing | None = None
    video_analysis: VideoAnalysisPricing | None = None


# Which pricing section each capability tag bills against.
_CAPABILITY_PRICING_SECTION: dict[str, str] = {
    Operation.TEXT_TO_IMAGE.value: "image",
    Operation.IMAGE_TO_IMAGE.value: "image",
    Operation.AUDIO_GENERATION.value: "audio",
    Operation.TEXT_TO_VIDEO.value: "video",
    Operation.IMAGE_TO_VIDEO.value: "video",
    Operation.VIDEO_TO_VIDEO.value: "video",
    Operation.VIDEO_ANALYSIS.value: "video_analysis",
}


def pricing_section_for(capability: str) -> str | None:
    """Which `MediaPricing` field prices this capability tag."""
    return _CAPABILITY_PRICING_SECTION.get(capability)


class LlmProviderEndpoint(ConfigSection):
    """One OpenAI/AiHubMix-compatible model provider endpoint.

    `kind="general"` is a text + vision LLM endpoint: every agent call
    (safety/planner/quality/copy) draws from this single shared pool via the
    failover logic in `app/llm/failover.py` — explicit primary/backup role +
    live concurrency + circuit-breaker state, no scoring formula. A general
    endpoint that also declares `"video"` in `input_modalities` plays a
    second, independent role: it additionally enters the `video_analysis`
    dynamic capability catalog (`app.providers.media_endpoints.
    dynamic_capabilities`) and gets scored/selected by `intent_router` like
    any media endpoint, while remaining a failover-pool member for its
    ordinary agent-call role. The two selection paths never interact.

    `kind="media"` is a media generation endpoint (image/video/audio). It is
    selected from the enabled endpoints maintained in Models; test fakes are
    never registered in this production directory.
    """

    name: str
    base_url: str
    # Accepted as plaintext on write; the admin API never echoes it back.
    api_key: str = ""
    kind: Literal["general", "media"] = "general"
    # Exactly one endpoint should hold "primary" among endpoints of the same
    # `kind`; the admin API enforces that by demoting the previous primary on
    # write.
    role: Literal["primary", "backup"] = "backup"
    # Only meaningful when role == "backup": lower tries first among backups.
    backup_order: int = Field(default=100, ge=1, le=1000)
    # The single model id this endpoint serves — for `kind="general"` the model
    # every bound agent call runs on, for `kind="media"` the model every derived
    # capability dispatches to. One credential serving several different model
    # ids means several endpoints, not several entries here: pricing, context
    # limits and cost accounting all hang off this one name.
    model: str = ""
    # `kind="media"`: subsets of `MEDIA_INPUT_MODALITIES`/`_OUTPUT_MODALITIES`.
    # `kind="general"`: subset of `{"text","image","video"}` — what the model
    # can read besides plain text. `"text"` is always present (auto-injected
    # by the validator below); `"image"` is a declarative label only (no
    # capability derives from it yet); `"video"` makes the endpoint a
    # `video_analysis` candidate — see `capabilities` and
    # `media_endpoints.dynamic_capabilities`.
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # `kind="media"` only: which HTTP contract this endpoint speaks. Missing
    # values are inferred from modalities so pre-protocol JSON still parses.
    protocol: MediaProtocol | None = None
    max_concurrency: int = Field(default=4, ge=1, le=256)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    enabled: bool = True
    # `kind="general"` only: what the model can hold and emit. Zero means the
    # operator has not declared it — shown as unknown in admin and treated as
    # "no declared ceiling" at call time (the request is honoured as-is). A
    # non-zero value *is* the ceiling: `output_budget` / `expand_output_budget`
    # use these instead of a code constant so a 4k model and a 128k model
    # cannot share one invented floor or retry cap.
    context_length: int = Field(default=0, ge=0, le=100_000_000)
    max_output_tokens: int = Field(default=0, ge=0, le=10_000_000)
    # `kind="general"` only: what this model's tokens cost us.
    token_pricing: TokenPricing = Field(default_factory=TokenPricing)
    # `kind="media"` only: per-capability list prices.
    media_pricing: MediaPricing = Field(default_factory=MediaPricing)

    @property
    def capabilities(self) -> set[str]:
        """Which `MEDIA_CAPABILITIES` tags this endpoint serves.

        Derived from `input_modalities`/`output_modalities`, not stored: a
        plain `@property` (not a pydantic field), so it never round-trips
        through `model_dump()` and can't go stale relative to the modalities
        that produced it.

        A `kind="general"` endpoint has no declared output modality (it is
        always a text-answering chat endpoint), so it can only ever derive
        `video_analysis` — the one capability whose output side is `"text"`
        — and only when it declares `"video"` on the input side.
        """
        if self.kind == "media":
            return capabilities_for_modalities(self.input_modalities, self.output_modalities)
        if self.kind == "general" and "video" in self.input_modalities:
            return {Operation.VIDEO_ANALYSIS.value}
        return set()

    def output_budget(
        self,
        requested: int,
        *,
        prompt_tokens: int = 0,
        reasoning_model: bool = False,
    ) -> int:
        """Completion tokens to ask this endpoint for.

        Declared `max_output_tokens` / `context_length` of 0 mean the
        operator has not filled them in — the request is honoured as-is,
        including for a reasoning model: there is no ceiling to add a
        thinking margin under, so inventing one here would be a made-up
        floor for a model nobody has told this endpoint's real limits.
        A reasoning model that *has* a declared ceiling gets `requested`
        plus `REASONING_THINKING_MARGIN_TOKENS` of headroom for hidden
        thinking, capped by that ceiling — not the ceiling itself, so a
        model spending an unusually long time thinking gets truncated (and,
        for a streaming caller, retried once — see `stream_complete`) well
        before the endpoint's full declared limit. Remaining context
        (`context_length - prompt_tokens`) is a second cap when the window
        is known.
        """
        budget = max(int(requested), 1)
        if self.max_output_tokens:
            if reasoning_model:
                budget += REASONING_THINKING_MARGIN_TOKENS
            budget = min(budget, self.max_output_tokens)
        if self.context_length:
            remaining = self.context_length - max(int(prompt_tokens), 0)
            if remaining > 0:
                budget = min(budget, remaining)
        return max(budget, 1)

    def expand_output_budget(self, current: int, *, prompt_tokens: int = 0) -> int:
        """One truncation retry: double, then re-apply this model's ceilings."""
        return self.output_budget(max(int(current), 1) * 2, prompt_tokens=prompt_tokens)

    @model_validator(mode="after")
    def _media_model_and_modalities_are_coherent(self) -> LlmProviderEndpoint:
        self.model = self.model.strip()
        if self.kind != "media":
            if not self.model:
                raise ValueError("通用模型端点必须填写模型名称。")
            self.protocol = None
            self.output_modalities = []
            bad = set(self.input_modalities) - set(GENERAL_INPUT_MODALITIES)
            if bad:
                raise ValueError(f"通用模型不支持的输入类型: {sorted(bad)}")
            # Text is the one input every chat endpoint always accepts —
            # never optional, so it is injected rather than required from
            # the caller.
            modalities = {"text", *self.input_modalities}
            self.input_modalities = [m for m in GENERAL_INPUT_MODALITIES if m in modalities]
            # A price for a capability this endpoint cannot produce would
            # still show up in cost reports and router estimates, same
            # reasoning as the media branch below.
            self.media_pricing = MediaPricing(
                video_analysis=(
                    self.media_pricing.video_analysis if "video" in self.input_modalities else None
                )
            )
            return self
        if not self.model:
            raise ValueError("媒体模型必须填写模型名称。")
        bad_inputs = set(self.input_modalities) - set(MEDIA_INPUT_MODALITIES)
        bad_outputs = set(self.output_modalities) - set(MEDIA_OUTPUT_MODALITIES)
        if bad_inputs or bad_outputs:
            raise ValueError(f"不支持的模态: {sorted(bad_inputs | bad_outputs)}")
        if not capabilities_for_modalities(self.input_modalities, self.output_modalities):
            raise ValueError("所选输入/输出类型组合未对应任何生成能力，请重新选择。")
        if self.protocol is None:
            self.protocol = infer_media_protocol(self.capabilities)
        if self.protocol not in IMPLEMENTED_MEDIA_PROTOCOLS:
            raise ValueError(f"接口协议尚未接入: {self.protocol}")
        allowed = PROTOCOL_CAPABILITIES.get(self.protocol, frozenset())
        if not self.capabilities <= allowed:
            raise ValueError("接口协议与所选输入/输出类型不匹配。")
        # Media routes are selected by capability and the intent router, not
        # by the LLM pool's primary/backup or concurrency lease semantics.
        self.role = "backup"
        self.backup_order = 100
        self.max_concurrency = 1
        self.context_length = 0
        self.max_output_tokens = 0
        self.token_pricing = TokenPricing()
        # A price for something this endpoint cannot produce would still show
        # up in cost reports and router estimates, so it is dropped rather
        # than carried along as dead configuration.
        priced = {pricing_section_for(tag) for tag in self.capabilities}
        self.media_pricing = MediaPricing(
            image=self.media_pricing.image if "image" in priced else None,
            audio=self.media_pricing.audio if "audio" in priced else None,
            video=self.media_pricing.video if "video" in priced else None,
            video_analysis=(
                self.media_pricing.video_analysis if "video_analysis" in priced else None
            ),
        )
        return self

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, data: Any) -> Any:
        """Reads pre-migration rows saved before `role`/`kind` existed, drops
        the pre-modality `capabilities` shape (each tag carrying its own
        `model`/`enabled`), and collapses the old multi-model `models` list.

        `priority == 1` becomes the primary; anything else becomes a backup
        ordered by its old priority value. `scenario_tags` (the old Agent-role
        categorisation) is simply dropped — every endpoint that had one is a
        `kind="general"` endpoint, which is already the default. The old
        `capabilities` dict cannot be losslessly converted to one model id
        plus modalities (it could name a different model per tag), so it is
        dropped rather than guessed at; an operator re-declares the endpoint
        once in the new form. Without this, `extra="forbid"` would make
        `get_typed` raise on any endpoint saved before this migration.

        An endpoint now serves exactly one model, so a legacy `models` list
        keeps its first entry — the same one `providers/connectivity.py` always
        treated as the endpoint's representative model. Dropping the rest is
        loud rather than silent: an operator re-adds them as their own
        endpoints, which is what per-model pricing needs anyway.
        """
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        migrated.pop("scenario_tags", None)
        migrated.pop("capabilities", None)
        legacy_models = migrated.pop("models", None)
        if isinstance(legacy_models, list) and not str(migrated.get("model") or "").strip():
            named = [str(name).strip() for name in legacy_models if str(name).strip()]
            if named:
                migrated["model"] = named[0]
                if len(named) > 1:
                    logger.warning(
                        "llm_providers endpoint declared %d models (%s); keeping %s — "
                        "re-add the others as their own endpoints",
                        len(named),
                        ", ".join(named),
                        named[0],
                    )
        if "priority" in migrated:
            legacy_priority = migrated.pop("priority")
            migrated.setdefault("role", "primary" if legacy_priority <= 1 else "backup")
            migrated.setdefault("backup_order", max(1, min(1000, legacy_priority)))
        kind = migrated.get("kind", "general")
        protocol = migrated.get("protocol")
        if kind != "media":
            migrated["protocol"] = None
        elif not (isinstance(protocol, str) and protocol.strip()):
            caps = capabilities_for_modalities(
                migrated.get("input_modalities") or [],
                migrated.get("output_modalities") or [],
            )
            migrated["protocol"] = infer_media_protocol(caps)
        return migrated


class LlmProviderConfig(ConfigSection):
    endpoints: dict[str, LlmProviderEndpoint] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _drop_invalid_endpoints(cls, data: Any) -> Any:
        """One bad media endpoint must not empty the whole pool.

        `get_typed` falls back to `DEFAULT_CONFIGS` (no endpoints) when this
        model fails to parse. Skipping the offender keeps the rest routable.
        """
        if not isinstance(data, dict):
            return data
        raw_endpoints = data.get("endpoints")
        if not isinstance(raw_endpoints, dict):
            return data
        kept: dict[str, Any] = {}
        for endpoint_id, raw in raw_endpoints.items():
            try:
                LlmProviderEndpoint.model_validate(raw)
            except Exception:
                logger.warning(
                    "dropping invalid llm_providers endpoint %s", endpoint_id, exc_info=True
                )
                continue
            kept[endpoint_id] = raw
        return {**data, "endpoints": kept}


CONFIG_SCHEMAS: dict[str, type[ConfigSection]] = {
    "pricing": PricingConfig,
    "royalty": RoyaltyConfig,
    "marketplace": MarketplaceConfig,
    "feature_flags": FeatureFlags,
    "content_moderation": ContentModerationConfig,
    "learning_moderation": LearningModerationConfig,
    "skill_moderation": SkillModerationConfig,
    "shortform": ShortformConfig,
    "llm_providers": LlmProviderConfig,
}


DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "pricing": {
        "tier_pricing": {
            Operation.TEXT_TO_IMAGE.value: {"preview": 4, "standard": 12, "cinematic": 40},
            Operation.IMAGE_TO_IMAGE.value: {"preview": 4, "standard": 12, "cinematic": 40},
            Operation.TEXT_TO_VIDEO.value: {"preview": 30, "standard": 90, "cinematic": 260},
            Operation.IMAGE_TO_VIDEO.value: {"preview": 26, "standard": 80, "cinematic": 240},
            Operation.VIDEO_TO_VIDEO.value: {"preview": 34, "standard": 100, "cinematic": 280},
            Operation.AUDIO_GENERATION.value: {"preview": 2, "standard": 6, "cinematic": 15},
            # Tiers map to analysis depth, not render quality: preview = one
            # overall summary, standard = a per-scene breakdown, cinematic =
            # a full shot-by-shot breakdown with transitions.
            Operation.VIDEO_ANALYSIS.value: {"preview": 20, "standard": 50, "cinematic": 120},
        },
        "video_base_seconds": 4,
        "video_per_second_surcharge": {"preview": 4, "standard": 12, "cinematic": 30},
    },
    "royalty": {
        "enabled": True,
        "first_level_rate_bps": 1000,
        "decay_bps": 5000,
        "max_levels": 3,
        "min_payout": 1,
        "total_cap_bps": 2000,
    },
    "marketplace": {
        "platform_fee_bps": 1000,
        "max_access_credits": 10_000,
    },
    "feature_flags": {
        "video_generation": True,
        "public_registration": True,
        "shortform_studio": True,
        "drama_studio_enabled": False,
        "web_editor_enabled": False,
        "variant_export_enabled": False,
        "editor_ai_enabled": False,
        "editor_mcp_enabled": False,
        "marketplace_enabled": True,
        "script_studio_enabled": False,
        "video_analysis_enabled": False,
        "rollout_percentages": {},
    },
    "content_moderation": {"blocked_keywords": []},
    "learning_moderation": {"blocked_keywords": []},
    "skill_moderation": {"blocked_keywords": []},
    "shortform": {
        "profiles": {
            "douyin_vertical": {
                "aspect_ratio": "9:16",
                "width": 1080,
                "height": 1920,
                "min_duration_seconds": 5,
                "max_duration_seconds": 30,
                "max_title_length": 55,
                "max_hashtags": 5,
                "safe_area_top_pct": 12,
                "safe_area_bottom_pct": 22,
                "safe_area_right_pct": 18,
                "require_ai_disclosure": True,
            },
            # Landscape keeps the same text limits; only the reserved overlay
            # shrinks, because the interaction bar is far narrower than it is
            # on a full-height vertical clip.
            "douyin_landscape": {
                "aspect_ratio": "16:9",
                "width": 1920,
                "height": 1080,
                "min_duration_seconds": 5,
                "max_duration_seconds": 30,
                "max_title_length": 55,
                "max_hashtags": 5,
                "safe_area_top_pct": 10,
                "safe_area_bottom_pct": 18,
                "safe_area_right_pct": 8,
                "require_ai_disclosure": True,
            },
        },
        "default_profile": "douyin_vertical",
        "enable_clarifying_questions": True,
        "enable_preview_picker": True,
        "preview_candidate_count": 3,
    },
    # Empty by default: with no endpoints configured, `app/llm/client.py` has
    # nothing to call and every request fails immediately until an operator
    # adds an endpoint at `/admin/models`. `make seed` bootstraps one from
    # `.env` for local development; see `app/scripts/seed.py`.
    "llm_providers": {
        "endpoints": {},
    },
}
