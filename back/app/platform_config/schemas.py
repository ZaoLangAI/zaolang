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


class FeatureFlags(ConfigSection):
    video_generation: bool = True
    public_registration: bool = True
    shortform_studio: bool = True
    drama_studio_enabled: bool = False
    web_editor_enabled: bool = False
    variant_export_enabled: bool = False
    editor_ai_enabled: bool = False
    editor_mcp_enabled: bool = False
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
MEDIA_OUTPUT_MODALITIES: list[str] = ["image", "video", "audio"]

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
IMPLEMENTED_MEDIA_PROTOCOLS: frozenset[str] = frozenset({"openai", "minimax"})
_OPENAI_CAPABILITIES = frozenset(
    {
        Operation.TEXT_TO_IMAGE.value,
        Operation.IMAGE_TO_IMAGE.value,
        Operation.AUDIO_GENERATION.value,
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
PROTOCOL_CAPABILITIES: dict[str, frozenset[str]] = {
    "openai": _OPENAI_CAPABILITIES,
    "minimax": _MINIMAX_CAPABILITIES,
    "comfyui": _COMFYUI_CAPABILITIES,
    "google": frozenset(),
    "dashscope": frozenset(),
    "ark": frozenset(),
    "kling": frozenset(),
}


def infer_media_protocol(capabilities: Iterable[str]) -> MediaProtocol:
    """Guess the contract for a pre-protocol media endpoint.

    Video-only → MiniMax (the only implemented video path). Anything else,
    including mixed image+video leftovers, → OpenAI so the after-validator
    can reject the mismatch instead of silently picking a vendor.
    """
    caps = set(capabilities)
    if caps and caps <= _MINIMAX_CAPABILITIES:
        return "minimax"
    return "openai"


class LlmProviderEndpoint(ConfigSection):
    """One OpenAI/AiHubMix-compatible model provider endpoint.

    `kind="general"` is a text + vision LLM endpoint: every agent call
    (safety/planner/quality/copy) draws from this single shared pool via the
    failover logic in `app/llm/failover.py` — explicit primary/backup role +
    live concurrency + circuit-breaker state, no scoring formula.

    `kind="media"` is a media generation endpoint (image/video/audio). It is
    selected from the enabled endpoints maintained in Models; test fakes are
    never registered in this production directory.
    """

    name: str
    base_url: str
    # Accepted as plaintext on write; the admin API never echoes it back.
    api_key: str = ""
    kind: Literal["general", "media"] = "general"
    # `kind="general"` only.
    models: list[str] = Field(default_factory=list)
    # Exactly one endpoint should hold "primary" among endpoints of the same
    # `kind`; the admin API enforces that by demoting the previous primary on
    # write.
    role: Literal["primary", "backup"] = "backup"
    # Only meaningful when role == "backup": lower tries first among backups.
    backup_order: int = Field(default=100, ge=1, le=1000)
    # `kind="media"` only: the single model id every derived capability below
    # dispatches to. One credential serving several different model ids means
    # several endpoints, not several entries here.
    model: str = ""
    # `kind="media"` only: subsets of `MEDIA_INPUT_MODALITIES`/`_OUTPUT_MODALITIES`.
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # `kind="media"` only: which HTTP contract this endpoint speaks. Missing
    # values are inferred from modalities so pre-protocol JSON still parses.
    protocol: MediaProtocol | None = None
    max_concurrency: int = Field(default=4, ge=1, le=256)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    enabled: bool = True

    @property
    def capabilities(self) -> set[str]:
        """Which `MEDIA_CAPABILITIES` tags this endpoint serves.

        Derived from `input_modalities`/`output_modalities`, not stored: a
        plain `@property` (not a pydantic field), so it never round-trips
        through `model_dump()` and can't go stale relative to the modalities
        that produced it.
        """
        if self.kind != "media":
            return set()
        return capabilities_for_modalities(self.input_modalities, self.output_modalities)

    @model_validator(mode="after")
    def _media_model_and_modalities_are_coherent(self) -> LlmProviderEndpoint:
        if self.kind != "media":
            if not self.models:
                raise ValueError("通用模型端点至少需要声明一个模型。")
            self.models = list(
                dict.fromkeys(model.strip() for model in self.models if model.strip())
            )
            if not self.models:
                raise ValueError("通用模型端点至少需要声明一个模型。")
            self.protocol = None
            return self
        if not self.model.strip():
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
        return self

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, data: Any) -> Any:
        """Reads pre-migration rows saved before `role`/`kind` existed, and
        drops the pre-modality `capabilities` shape (each tag carrying its own
        `model`/`enabled`).

        `priority == 1` becomes the primary; anything else becomes a backup
        ordered by its old priority value. `scenario_tags` (the old Agent-role
        categorisation) is simply dropped — every endpoint that had one is a
        `kind="general"` endpoint, which is already the default. The old
        `capabilities` dict cannot be losslessly converted to one model id
        plus modalities (it could name a different model per tag), so it is
        dropped rather than guessed at; an operator re-declares the endpoint
        once in the new form. Without this, `extra="forbid"` would make
        `get_typed` raise on any endpoint saved before this migration.
        """
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        migrated.pop("scenario_tags", None)
        migrated.pop("capabilities", None)
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
    "feature_flags": {
        "video_generation": True,
        "public_registration": True,
        "shortform_studio": True,
        "drama_studio_enabled": False,
        "web_editor_enabled": False,
        "variant_export_enabled": False,
        "editor_ai_enabled": False,
        "editor_mcp_enabled": False,
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
    # nothing to call and degrades every request straight to the stub (or
    # errors in `openai_compatible` mode) until an operator adds an endpoint
    # at `/admin/models`. `make seed` bootstraps one from `.env` for local
    # development; see `app/scripts/seed.py`.
    "llm_providers": {
        "endpoints": {},
    },
}
