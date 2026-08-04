"""Runtime configuration: validation, versioning, rollback and flag rollout."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.models import PlatformConfig, User
from app.platform_config import service as config_service
from app.platform_config.schemas import (
    DEFAULT_CONFIGS,
    MAX_GENERATION_DURATION_SECONDS,
    AgentConfig,
    FeatureFlags,
    PricingConfig,
    RoutingWeights,
    ShortformConfig,
)


def test_an_unset_key_falls_back_to_the_built_in_default(db: Session) -> None:
    assert config_service.get_raw(db, "pricing") == DEFAULT_CONFIGS["pricing"]


def test_writing_a_value_creates_version_one(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["routing_weights"])
    value["quality"] = 0.5
    value["cost"] = 0.15

    row = config_service.set_value(db, "routing_weights", value, actor_user_id=admin.id)
    assert row.version == 1
    assert row.is_active is True
    assert config_service.get_typed(db, "routing_weights", RoutingWeights).quality == 0.5


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


def test_routing_weights_must_sum_to_one(db: Session, admin: User) -> None:
    """Scores from differently-weighted candidates would not be comparable."""
    with pytest.raises(ValidationFailed):
        config_service.set_value(
            db,
            "routing_weights",
            {"quality": 0.9, "latency": 0.9, "cost": 0.1, "reliability": 0.1},
            actor_user_id=admin.id,
        )


def test_tier_pricing_must_increase_with_quality(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["pricing"])
    value["tier_pricing"]["text_to_image"] = {"preview": 40, "standard": 12, "cinematic": 4}

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "pricing", value, actor_user_id=admin.id)


def test_an_unknown_key_is_rejected(db: Session, admin: User) -> None:
    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "not_a_real_key", {}, actor_user_id=admin.id)


def test_every_agent_must_stay_bound_to_a_model(db: Session, admin: User) -> None:
    """An unbound agent would fail at generation time rather than at edit time."""
    value = copy.deepcopy(DEFAULT_CONFIGS["agents"])
    del value["bindings"]["safety"]

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "agents", value, actor_user_id=admin.id)


def test_an_agent_model_can_be_switched_without_a_restart(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["agents"])
    value["bindings"]["safety"]["model"] = "kimi-k3"
    config_service.set_value(db, "agents", value, actor_user_id=admin.id)

    bindings = config_service.get_typed(db, "agents", AgentConfig).bindings
    assert bindings["safety"].model == "kimi-k3"


def test_a_disabled_flag_is_off_for_everyone(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["royalties"] = False
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    assert config_service.is_enabled(db, "royalties") is False
    assert config_service.is_enabled(db, "royalties", user_id="usr_anything") is False


def test_rollout_bucketing_is_stable_for_a_given_user(db: Session, admin: User) -> None:
    """A user whose bucket flipped between requests would see the feature appear
    and vanish at random."""
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"semantic_search": 50}
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    first = config_service.is_enabled(db, "semantic_search", user_id="usr_stable_1")
    for _ in range(5):
        assert config_service.is_enabled(db, "semantic_search", user_id="usr_stable_1") is first


def test_a_partial_rollout_excludes_anonymous_callers(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"command_palette": 10}
    config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)

    assert config_service.is_enabled(db, "command_palette", user_id=None) is False


def test_rollout_percentages_stay_within_range(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["rollout_percentages"] = {"semantic_search": 140}

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)


def test_unknown_fields_are_rejected_rather_than_silently_dropped(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["feature_flags"])
    value["typo_flag"] = True

    with pytest.raises(ValidationFailed):
        config_service.set_value(db, "feature_flags", value, actor_user_id=admin.id)


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
