"""Runtime configuration: validation, versioning, rollback and flag rollout."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.models import PlatformConfig, User
from app.models.enums import Operation
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    DEFAULT_CONFIGS,
    MAX_GENERATION_DURATION_SECONDS,
    PROTOCOL_CAPABILITIES,
    ContentModerationConfig,
    FeatureFlags,
    LlmProviderConfig,
    LlmProviderEndpoint,
    PricingConfig,
    ShortformConfig,
)


def test_an_unset_key_falls_back_to_the_built_in_default(db: Session) -> None:
    assert config_service.get_raw(db, "pricing") == DEFAULT_CONFIGS["pricing"]


def test_writing_a_value_creates_version_one(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["pricing"])
    value["video_base_seconds"] = 6

    row = config_service.set_value(db, "pricing", value, actor_user_id=admin.id)
    assert row.version == 1
    assert row.is_active is True
    assert config_service.get_typed(db, "pricing", PricingConfig).video_base_seconds == 6


def test_a_second_write_deactivates_the_previous_version(db: Session, admin: User) -> None:
    """Exactly one version is active at a time, which is what makes reads
    unambiguous and rollback meaningful."""
    first = copy.deepcopy(DEFAULT_CONFIGS["royalty"])
    first["first_level_rate_bps"] = 1200
    config_service.set_value(db, "royalty", first, actor_user_id=admin.id)

    second = copy.deepcopy(first)
    second["first_level_rate_bps"] = 1500
    config_service.set_value(db, "royalty", second, actor_user_id=admin.id)

    active = list(
        db.scalars(
            select(PlatformConfig).where(
                PlatformConfig.key == "royalty", PlatformConfig.is_active.is_(True)
            )
        )
    )
    assert len(active) == 1
    assert active[0].version == 2


def test_rollback_moves_forward_to_a_copy_of_the_old_value(db: Session, admin: User) -> None:
    """History is never rewritten, so the audit trail keeps both the mistake and
    the correction."""
    original = copy.deepcopy(DEFAULT_CONFIGS["royalty"])
    original["max_levels"] = 2
    config_service.set_value(db, "royalty", original, actor_user_id=admin.id)

    broken = copy.deepcopy(original)
    broken["max_levels"] = 9
    config_service.set_value(db, "royalty", broken, actor_user_id=admin.id)

    restored = config_service.rollback(db, "royalty", 1, actor_user_id=admin.id)
    assert restored.version == 3
    assert restored.value_json["max_levels"] == 2
    assert len(config_service.history(db, "royalty")) == 3


def test_rollback_to_an_unknown_version_is_refused(db: Session, admin: User) -> None:
    with pytest.raises(NotFound):
        config_service.rollback(db, "royalty", 99, actor_user_id=admin.id)


def test_tier_pricing_must_increase_with_quality(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["pricing"])
    value["tier_pricing"]["text_to_image"] = {"preview": 40, "standard": 12, "cinematic": 4}

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "pricing", value, actor_user_id=admin.id)


def test_an_unknown_key_is_rejected(db: Session, admin: User) -> None:
    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "not_a_real_key", {}, actor_user_id=admin.id)


def test_a_disabled_flag_is_off_for_everyone(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["video_generation"] = False
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    assert config_service.is_enabled(db, "video_generation") is False
    assert config_service.is_enabled(db, "video_generation", user_id="usr_anything") is False


def test_rollout_bucketing_is_stable_for_a_given_user(db: Session, admin: User) -> None:
    """A user whose bucket flipped between requests would see the feature appear
    and vanish at random."""
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"video_generation": 50}
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    first = config_service.is_enabled(db, "video_generation", user_id="usr_stable_1")
    for _ in range(5):
        assert config_service.is_enabled(db, "video_generation", user_id="usr_stable_1") is first


def test_a_partial_rollout_excludes_anonymous_callers(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"shortform_studio": 10}
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    assert config_service.is_enabled(db, "shortform_studio", user_id=None) is False


def test_rollout_percentages_stay_within_range(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"video_generation": 140}

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)


def test_unknown_fields_are_rejected_rather_than_silently_dropped(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["typo_flag"] = True

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)


def test_public_registration_does_not_allow_rollout(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"public_registration": 50}
    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)


def test_moderation_keywords_are_normalised_and_deduplicated(db: Session, admin: User) -> None:
    config_service.set_value(
        db,
        "content_moderation",
        {"blocked_keywords": ["  Bad ", "bad", "BAD", ""]},
        actor_user_id=admin.id,
    )
    config = config_service.get_typed(db, "content_moderation", ContentModerationConfig)
    assert config.blocked_keywords == ["bad"]


def test_pricing_requires_every_operation(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["pricing"])
    value["tier_pricing"].pop("audio_generation")
    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "pricing", value, actor_user_id=admin.id)


def test_a_stored_value_that_no_longer_parses_falls_back_to_defaults(
    db: Session, admin: User
) -> None:
    """Tightening a schema must not take the service down on the next read."""
    config_service.set_value(
        db, "pricing", copy.deepcopy(DEFAULT_CONFIGS["pricing"]), actor_user_id=admin.id
    )
    row = db.scalar(
        select(PlatformConfig).where(
            PlatformConfig.key == "pricing", PlatformConfig.is_active.is_(True)
        )
    )
    assert row is not None
    row.value_json = {"tier_pricing": "nonsense"}
    db.flush()
    config_service.invalidate("pricing")

    pricing = config_service.get_typed(db, "pricing", PricingConfig)
    assert pricing.tier_pricing == DEFAULT_CONFIGS["pricing"]["tier_pricing"]


def test_the_shortform_catalogue_ships_a_vertical_and_a_landscape_spec(db: Session) -> None:
    config = config_service.get_typed(db, "shortform", ShortformConfig)

    assert config.default_profile == "douyin_vertical"
    assert config.profiles["douyin_vertical"].aspect_ratio == "9:16"
    assert config.profiles["douyin_landscape"].aspect_ratio == "16:9"


def test_no_shortform_spec_asks_for_more_than_a_job_can_be_submitted_for(db: Session) -> None:
    """A spec longer than the submission ceiling would be unreachable: every
    job matching it would be refused at 422."""
    config = config_service.get_typed(db, "shortform", ShortformConfig)

    for key, profile in config.profiles.items():
        assert profile.max_duration_seconds <= MAX_GENERATION_DURATION_SECONDS, key
        assert profile.min_duration_seconds <= profile.max_duration_seconds, key


def test_the_default_shortform_profile_must_exist(db: Session, admin: User) -> None:
    """Otherwise every studio session would 422 on a spec nobody can select."""
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["default_profile"] = "tiktok_square"

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "shortform", value, actor_user_id=admin.id)


def test_a_shortform_spec_cannot_exceed_the_submission_ceiling(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["profiles"]["douyin_vertical"]["max_duration_seconds"] = 90

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "shortform", value, actor_user_id=admin.id)


def test_a_shortform_spec_with_an_inverted_duration_range_is_refused(
    db: Session, admin: User
) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["profiles"]["douyin_vertical"]["min_duration_seconds"] = 20
    value["profiles"]["douyin_vertical"]["max_duration_seconds"] = 10

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "shortform", value, actor_user_id=admin.id)


def test_a_new_shortform_spec_takes_effect_without_a_restart(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["profiles"]["douyin_square"] = {
        **value["profiles"]["douyin_vertical"],
        "aspect_ratio": "1:1",
        "width": 1080,
        "height": 1080,
    }
    config_service.set_value(db, "shortform", value, actor_user_id=admin.id)

    profiles = config_service.get_typed(db, "shortform", ShortformConfig).profiles
    assert profiles["douyin_square"].aspect_ratio == "1:1"
    assert profiles["douyin_square"].max_title_length == 55


def test_the_clarify_and_preview_toggles_default_on_with_three_candidates(
    db: Session,
) -> None:
    config = config_service.get_typed(db, "shortform", ShortformConfig)

    assert config.enable_clarifying_questions is True
    assert config.enable_preview_picker is True
    assert config.preview_candidate_count == 3


def test_the_preview_candidate_count_cannot_exceed_three(db: Session, admin: User) -> None:
    """A guard rail: a fat-fingered edit must not silently multiply everyone's
    preview cost."""
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["preview_candidate_count"] = 5

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "shortform", value, actor_user_id=admin.id)


def test_the_preview_picker_can_be_switched_off_independently_of_clarify(
    db: Session, admin: User
) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["enable_preview_picker"] = False
    config_service.set_value(db, "shortform", value, actor_user_id=admin.id)

    config = config_service.get_typed(db, "shortform", ShortformConfig)
    assert config.enable_preview_picker is False
    assert config.enable_clarifying_questions is True


def test_the_shortform_studio_flag_can_be_turned_off(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["shortform_studio"] = False
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    assert config_service.is_enabled(db, "shortform_studio") is False


def test_the_video_surcharge_must_cover_every_tier(db: Session, admin: User) -> None:
    """A missing tier here would silently price a long video at the short price."""
    value = copy.deepcopy(DEFAULT_CONFIGS["pricing"])
    del value["video_per_second_surcharge"]["cinematic"]

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "pricing", value, actor_user_id=admin.id)


def test_all_known_keys_expose_a_schema(db: Session) -> None:
    for key in config_service.all_keys():
        assert config_service.get_raw(db, key) is not None
    assert set(config_service.all_keys()) == set(DEFAULT_CONFIGS)


def test_defaults_satisfy_their_own_schemas() -> None:
    """A default that fails validation would make every fallback path a 500."""
    for key in config_service.all_keys():
        config_service.validate(key, DEFAULT_CONFIGS[key])
    FeatureFlags.model_validate(DEFAULT_CONFIGS["feature_flags"])


def test_a_media_endpoint_without_protocol_infers_openai_for_images() -> None:
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "图",
            "base_url": "https://media.invalid",
            "kind": "media",
            "model": "qianfan/qwen-image-3.0",
            "input_modalities": ["text", "image"],
            "output_modalities": ["image"],
        }
    )
    assert endpoint.protocol == "openai"


def test_a_media_endpoint_without_protocol_infers_minimax_for_video_only() -> None:
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "视频",
            "base_url": "https://media.invalid",
            "kind": "media",
            "model": "minimax-h3",
            "input_modalities": ["text", "image", "video"],
            "output_modalities": ["video"],
        }
    )
    assert endpoint.protocol == "minimax"


def test_unimplemented_and_mismatched_protocols_are_rejected() -> None:
    with pytest.raises(Exception, match="尚未接入"):
        LlmProviderEndpoint.model_validate(
            {
                "name": "Comfy",
                "base_url": "https://comfy.invalid",
                "kind": "media",
                "model": "sdxl",
                "protocol": "comfyui",
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            }
        )
    with pytest.raises(Exception, match="不匹配"):
        LlmProviderEndpoint.model_validate(
            {
                "name": "错配",
                "base_url": "https://media.invalid",
                "kind": "media",
                "model": "gpt-image-1",
                "protocol": "openai",
                "input_modalities": ["text"],
                "output_modalities": ["video"],
            }
        )


def test_a_mixed_media_endpoint_is_dropped_without_emptying_the_pool() -> None:
    """`get_typed` must not fall back to the empty default because one
    leftover endpoint spans image and video capabilities."""
    parsed = LlmProviderConfig.model_validate(
        {
            "endpoints": {
                "good": {
                    "name": "图",
                    "base_url": "https://image.invalid",
                    "kind": "media",
                    "model": "gpt-image-1",
                    "input_modalities": ["text"],
                    "output_modalities": ["image"],
                },
                "mixed": {
                    "name": "混合",
                    "base_url": "https://mixed.invalid",
                    "kind": "media",
                    "model": "multi",
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["image", "video"],
                },
            }
        }
    )
    assert set(parsed.endpoints) == {"good"}
    assert parsed.endpoints["good"].protocol == "openai"


def test_a_general_endpoint_always_has_text_input_modality() -> None:
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "通用",
            "base_url": "https://general.invalid",
            "kind": "general",
            "model": "gpt-4o-mini",
        }
    )
    assert endpoint.input_modalities == ["text"]
    assert endpoint.capabilities == set()


def test_a_general_endpoint_declaring_video_derives_video_analysis() -> None:
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "通用带视频",
            "base_url": "https://general.invalid",
            "kind": "general",
            "model": "qwen-vl-max",
            "input_modalities": ["video"],
        }
    )
    # Text is injected even though the caller only asked for video.
    assert endpoint.input_modalities == ["text", "video"]
    assert endpoint.capabilities == {"video_analysis"}
    assert endpoint.output_modalities == []
    assert endpoint.protocol is None


def test_a_general_endpoint_rejects_unsupported_input_modalities() -> None:
    with pytest.raises(Exception, match="不支持的输入类型"):
        LlmProviderEndpoint.model_validate(
            {
                "name": "非法",
                "base_url": "https://general.invalid",
                "kind": "general",
                "model": "gpt-4o-mini",
                "input_modalities": ["audio"],
            }
        )


def test_a_general_endpoints_video_analysis_price_is_dropped_without_video_declared() -> None:
    """A price for a capability this endpoint cannot produce would still show
    up in cost reports and router estimates — same reasoning as the media
    branch's price-dropping behaviour."""
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "通用无视频",
            "base_url": "https://general.invalid",
            "kind": "general",
            "model": "gpt-4o-mini",
            "media_pricing": {"video_analysis": {"per_request_micro_usd": 80_000}},
        }
    )
    assert endpoint.media_pricing.video_analysis is None

    priced = LlmProviderEndpoint.model_validate(
        {
            "name": "通用带视频价格",
            "base_url": "https://general.invalid",
            "kind": "general",
            "model": "qwen-vl-max",
            "input_modalities": ["video"],
            "media_pricing": {"video_analysis": {"per_request_micro_usd": 80_000}},
        }
    )
    assert priced.media_pricing.video_analysis is not None
    assert priced.media_pricing.video_analysis.per_request_micro_usd == 80_000


def test_legacy_media_json_without_protocol_still_loads_via_get_typed(db: Session) -> None:
    """A stored pre-protocol endpoint must not trip `get_typed` into the empty
    default pool — that would silently unroute every media job."""
    from app.models import PlatformConfig
    from app.models.base import utcnow

    config_service.invalidate("llm_providers")
    db.add(
        PlatformConfig(
            key="llm_providers",
            version=1,
            is_active=True,
            value_json={
                "endpoints": {
                    "legacy-image": {
                        "name": "图",
                        "base_url": "https://image.invalid",
                        "api_key": "k",
                        "kind": "media",
                        "model": "gpt-image-1",
                        "input_modalities": ["text"],
                        "output_modalities": ["image"],
                    }
                }
            },
            created_at=utcnow(),
        )
    )
    db.flush()
    config_service.invalidate("llm_providers")
    config = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    assert "legacy-image" in config.endpoints
    assert config.endpoints["legacy-image"].protocol == "openai"


def test_comfyui_protocol_capabilities_exclude_audio() -> None:
    """Union-then-subtract; `|` binds looser than `-`, so parentheses matter."""
    caps = PROTOCOL_CAPABILITIES["comfyui"]
    assert Operation.AUDIO_GENERATION.value not in caps
    assert Operation.TEXT_TO_IMAGE.value in caps
    assert Operation.TEXT_TO_VIDEO.value in caps


def _general_endpoint(**kwargs: object) -> LlmProviderEndpoint:
    return LlmProviderEndpoint.model_validate(
        {
            "name": "通用",
            "base_url": "https://example.invalid/v1",
            "api_key": "k",
            "kind": "general",
            "model": "glm-5.3-flash",
            **kwargs,
        }
    )


def test_output_budget_honours_an_undeclared_ceiling() -> None:
    endpoint = _general_endpoint()
    assert endpoint.output_budget(2048, reasoning_model=True) == 2048
    assert endpoint.expand_output_budget(2048) == 4096


def test_output_budget_adds_a_thinking_margin_for_reasoning_capped_by_the_ceiling() -> None:
    """A reasoning model's first attempt gets the requested budget plus
    `REASONING_THINKING_MARGIN_TOKENS` of headroom, not the endpoint's
    entire declared ceiling — see `output_budget`'s own docstring for why
    handing over the full ceiling upfront is the behavior this replaced."""
    from app.platform_config.schemas import REASONING_THINKING_MARGIN_TOKENS

    endpoint = _general_endpoint(max_output_tokens=16_384)
    assert endpoint.output_budget(512, reasoning_model=True) == 512 + REASONING_THINKING_MARGIN_TOKENS
    assert endpoint.output_budget(512, reasoning_model=False) == 512
    # A request already close to (or past) the ceiling still gets capped by
    # it, margin included.
    assert endpoint.output_budget(20_000, reasoning_model=True) == 16_384
    assert endpoint.output_budget(20_000) == 16_384


def test_output_budget_caps_to_remaining_context() -> None:
    endpoint = _general_endpoint(context_length=1000, max_output_tokens=8000)
    assert endpoint.output_budget(4096, prompt_tokens=900) == 100
    assert endpoint.expand_output_budget(80, prompt_tokens=900) == 100
