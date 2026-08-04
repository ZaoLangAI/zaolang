"""Typed schemas for every runtime-configurable key.

Config is validated on write, not on read. An operator who submits a bad
routing weight gets a 422 at edit time; the workers never have to defend
against a malformed value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AgentName, Operation, QualityTier

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


class RoutingWeights(ConfigSection):
    """Router scoring weights. Must sum to 1 so scores stay comparable."""

    quality: float = Field(default=0.4, ge=0, le=1)
    latency: float = Field(default=0.2, ge=0, le=1)
    cost: float = Field(default=0.25, ge=0, le=1)
    reliability: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> RoutingWeights:
        total = self.quality + self.latency + self.cost + self.reliability
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"路由权重之和必须为 1，当前为 {total:.4f}。")
        return self


class ProviderSetting(ConfigSection):
    enabled: bool = True
    daily_job_limit: int = Field(default=0, ge=0)
    max_concurrency: int = Field(default=4, ge=1, le=256)
    # Multiplies the observed failure rate when estimating effective cost.
    retry_amplification: float = Field(default=1.2, ge=1.0, le=5.0)


class ProviderConfig(ConfigSection):
    providers: dict[str, ProviderSetting]
    # Applied when a provider has too few samples to trust its own statistics.
    conservative_prior_success_rate: float = Field(default=0.8, ge=0.1, le=1.0)
    minimum_samples_for_stats: int = Field(default=20, ge=1)


class AgentModelBinding(ConfigSection):
    model: str
    max_tokens: int = Field(default=1024, ge=64, le=32_768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Reasoning models spend part of the budget on hidden thinking, so their
    # ceiling has to be raised well above the visible output length.
    reasoning_model: bool = False


class AgentConfig(ConfigSection):
    bindings: dict[str, AgentModelBinding]

    @model_validator(mode="after")
    def _all_agents_bound(self) -> AgentConfig:
        missing = {a.value for a in AgentName} - set(self.bindings)
        if missing:
            raise ValueError(f"缺少智能体模型绑定: {sorted(missing)}")
        return self


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

    @model_validator(mode="after")
    def _default_profile_exists(self) -> ShortformConfig:
        if not self.profiles:
            raise ValueError("至少需要一个短视频规格。")
        if self.default_profile not in self.profiles:
            raise ValueError(f"默认规格 {self.default_profile} 不在规格目录中。")
        return self


class FeatureFlags(ConfigSection):
    semantic_search: bool = True
    style_presets: bool = True
    royalties: bool = True
    command_palette: bool = True
    video_generation: bool = True
    public_registration: bool = True
    shortform_studio: bool = True
    # Rollout percentage keyed by flag name, evaluated per user id hash.
    rollout_percentages: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _percentages_in_range(self) -> FeatureFlags:
        for name, pct in self.rollout_percentages.items():
            if not 0 <= pct <= 100:
                raise ValueError(f"灰度比例 {name}={pct} 必须在 0-100 之间。")
        return self


class ModerationConfig(ConfigSection):
    blocked_keywords: list[str] = Field(default_factory=list)
    auto_review_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    require_human_review_for_video: bool = True


CONFIG_SCHEMAS: dict[str, type[ConfigSection]] = {
    "pricing": PricingConfig,
    "routing_weights": RoutingWeights,
    "providers": ProviderConfig,
    "agents": AgentConfig,
    "royalty": RoyaltyConfig,
    "feature_flags": FeatureFlags,
    "moderation": ModerationConfig,
    "shortform": ShortformConfig,
}


DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "pricing": {
        "tier_pricing": {
            Operation.TEXT_TO_IMAGE.value: {"preview": 4, "standard": 12, "cinematic": 40},
            Operation.TEXT_TO_VIDEO.value: {"preview": 30, "standard": 90, "cinematic": 260},
            Operation.IMAGE_TO_VIDEO.value: {"preview": 26, "standard": 80, "cinematic": 240},
            Operation.VIDEO_TO_VIDEO.value: {"preview": 34, "standard": 100, "cinematic": 280},
        },
        "video_base_seconds": 4,
        "video_per_second_surcharge": {"preview": 4, "standard": 12, "cinematic": 30},
    },
    "routing_weights": {"quality": 0.4, "latency": 0.2, "cost": 0.25, "reliability": 0.15},
    "providers": {
        "providers": {
            "fake_open_workflow": {
                "enabled": True,
                "daily_job_limit": 0,
                "max_concurrency": 4,
                "retry_amplification": 1.2,
            },
            "fake_paid_api": {
                "enabled": True,
                "daily_job_limit": 500,
                "max_concurrency": 8,
                "retry_amplification": 1.1,
            },
        },
        "conservative_prior_success_rate": 0.8,
        "minimum_samples_for_stats": 20,
    },
    "agents": {
        "bindings": {
            # Clean JSON output matters most for a hard safety verdict.
            AgentName.SAFETY.value: {
                "model": "doubao-seed-2-1-pro",
                "max_tokens": 1024,
                "temperature": 0.0,
                "reasoning_model": False,
            },
            AgentName.PLANNER.value: {
                "model": "kimi-k3",
                "max_tokens": 2048,
                "temperature": 0.3,
                "reasoning_model": True,
            },
            AgentName.QUALITY.value: {
                "model": "kimi-k3",
                "max_tokens": 1536,
                "temperature": 0.1,
                "reasoning_model": True,
            },
            AgentName.COPY.value: {
                "model": "ling-3.0-flash-free",
                "max_tokens": 4096,
                "temperature": 0.7,
                "reasoning_model": True,
            },
        }
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
        "semantic_search": True,
        "style_presets": True,
        "royalties": True,
        "command_palette": True,
        "video_generation": True,
        "public_registration": True,
        "shortform_studio": True,
        "rollout_percentages": {},
    },
    "moderation": {
        "blocked_keywords": [],
        "auto_review_threshold": 0.7,
        "require_human_review_for_video": True,
    },
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
    },
}
