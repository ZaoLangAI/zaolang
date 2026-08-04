"""Short-video spec resolution and the submit-time consistency guard."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed
from app.domain.shortform import service as shortform
from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import DEFAULT_CONFIGS


def test_an_absent_profile_key_resolves_to_the_configured_default(db: Session) -> None:
    key, profile = shortform.resolve_profile(db, None)

    assert key == "douyin_vertical"
    assert profile.aspect_ratio == "9:16"


def test_an_unknown_profile_names_the_ones_that_exist(db: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        shortform.resolve_profile(db, "kuaishou_vertical")

    assert "douyin_vertical" in excinfo.value.details["available"]


def test_params_without_a_profile_are_left_alone(db: Session) -> None:
    """Ordinary generation must not acquire short-video rules by accident."""
    shortform.assert_params_consistent(db, {"aspect_ratio": "16:9", "duration_seconds": 0})


def test_a_matching_pair_of_params_is_accepted(db: Session) -> None:
    shortform.assert_params_consistent(
        db,
        {"shortform_profile": "douyin_vertical", "aspect_ratio": "9:16", "duration_seconds": 15},
    )


def test_a_contradicting_aspect_ratio_is_refused(db: Session) -> None:
    """Caught before quoting: a mismatch must not cost the user a reservation."""
    with pytest.raises(ValidationFailed) as excinfo:
        shortform.assert_params_consistent(
            db,
            {
                "shortform_profile": "douyin_vertical",
                "aspect_ratio": "16:9",
                "duration_seconds": 15,
            },
        )

    assert "params.aspect_ratio" in excinfo.value.details["fields"]


def test_a_duration_outside_the_spec_is_refused(db: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        shortform.assert_params_consistent(
            db,
            {
                "shortform_profile": "douyin_vertical",
                "aspect_ratio": "9:16",
                "duration_seconds": 2,
            },
        )

    assert "params.duration_seconds" in excinfo.value.details["fields"]


def test_the_rules_follow_a_reconfigured_spec(db: Session, admin: User) -> None:
    value = copy.deepcopy(DEFAULT_CONFIGS["shortform"])
    value["profiles"]["douyin_vertical"]["min_duration_seconds"] = 15
    config_service.set_value(db, "shortform", value, actor_user_id=admin.id)

    params = {
        "shortform_profile": "douyin_vertical",
        "aspect_ratio": "9:16",
        "duration_seconds": 10,
    }
    with pytest.raises(ValidationFailed):
        shortform.assert_params_consistent(db, params)


@pytest.mark.parametrize(
    ("width", "height", "ratio", "expected"),
    [
        (1080, 1920, "9:16", True),
        # Encoder rounding, not a different aspect ratio.
        (1078, 1920, "9:16", True),
        (1920, 1080, "9:16", False),
        (1080, 1080, "1:1", True),
        (1080, 1920, "not-a-ratio", False),
    ],
)
def test_aspect_matching_tolerates_rounding_but_not_the_wrong_shape(
    width: int, height: int, ratio: str, expected: bool
) -> None:
    assert shortform._matches_aspect(width, height, ratio) is expected
