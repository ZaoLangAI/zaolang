"""`GenerationJobCreateRequest` validation for the two new media operations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas.jobs import (
    DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS,
    GenerationJobCreateRequest,
    GenerationParams,
    VideoGenerationOptions,
    apply_sandbox_generation_defaults,
    prepare_sandbox_generation_params,
    validate_generation_params,
)
from app.models.enums import Operation, QualityTier


def _request(operation: str, **param_overrides: object) -> GenerationJobCreateRequest:
    params = GenerationParams(prompt="测试提示词", **param_overrides)
    return GenerationJobCreateRequest(
        operation=operation, quality_tier=QualityTier.STANDARD, params=params
    )


def test_image_to_image_requires_a_reference_image() -> None:
    with pytest.raises(ValidationError, match="图生图必须提供参考图"):
        _request(Operation.IMAGE_TO_IMAGE)

    request = _request(Operation.IMAGE_TO_IMAGE, reference_asset_ids=["asset-1"])
    assert request.operation == Operation.IMAGE_TO_IMAGE


def test_audio_generation_requires_a_recognised_voice() -> None:
    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION)

    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION, extra={"voice": "not-a-real-voice"})

    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "nova"})
    assert request.operation == Operation.AUDIO_GENERATION


def test_audio_generation_does_not_require_a_duration() -> None:
    """Unlike the video operations, a zero duration is fine here."""
    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "alloy"}, duration_seconds=0)
    assert request.params.duration_seconds == 0


def test_image_to_image_does_not_require_a_duration() -> None:
    request = _request(
        Operation.IMAGE_TO_IMAGE, reference_asset_ids=["asset-1"], duration_seconds=0
    )
    assert request.params.duration_seconds == 0


def test_h3_video_options_accept_the_documented_range_and_aspects() -> None:
    request = _request(
        Operation.TEXT_TO_VIDEO,
        duration_seconds=4,
        aspect_ratio="21:9",
        video_options={"resolution": "2K", "reference_mode": "input_references"},
    )
    assert request.params.video_options is not None
    assert request.params.video_options.resolution == "2K"

    with pytest.raises(ValidationError, match="4-15"):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=16,
            video_options={"resolution": "2K"},
        )


def test_h3_frame_images_require_a_first_frame_and_exclude_other_references() -> None:
    request = _request(
        Operation.IMAGE_TO_VIDEO,
        duration_seconds=5,
        video_options={
            "reference_mode": "frame_images",
            "first_frame_asset_id": "asset-first",
            "last_frame_asset_id": "asset-last",
        },
    )
    assert request.params.video_options is not None
    assert request.params.video_options.last_frame_asset_id == "asset-last"

    with pytest.raises(ValidationError, match="首尾帧与普通参考素材"):
        _request(
            Operation.IMAGE_TO_VIDEO,
            duration_seconds=5,
            reference_asset_ids=["asset-reference"],
            video_options={
                "reference_mode": "frame_images",
                "first_frame_asset_id": "asset-first",
            },
        )

    with pytest.raises(ValidationError, match="必须提供首帧"):
        _request(
            Operation.IMAGE_TO_VIDEO,
            duration_seconds=5,
            video_options={"reference_mode": "frame_images"},
        )


def test_validate_generation_params_rejects_a_zero_video_duration() -> None:
    with pytest.raises(ValueError, match="视频生成必须指定时长"):
        validate_generation_params(Operation.TEXT_TO_VIDEO, duration_seconds=0)


def test_validate_generation_params_rejects_h3_duration_out_of_range() -> None:
    with pytest.raises(ValueError, match="4-15"):
        validate_generation_params(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=16,
            video_options=VideoGenerationOptions(),
        )


def test_sandbox_defaults_fill_an_omitted_video_duration_then_pass_validation() -> None:
    filled = apply_sandbox_generation_defaults(Operation.TEXT_TO_VIDEO, {"prompt": "香港街道"})
    assert filled["duration_seconds"] == DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS
    validate_generation_params(Operation.TEXT_TO_VIDEO, duration_seconds=filled["duration_seconds"])

    prepared = prepare_sandbox_generation_params(Operation.TEXT_TO_VIDEO, {"prompt": "香港街道"})
    assert prepared["duration_seconds"] == DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS
    assert prepared["prompt"] == "香港街道"


def test_sandbox_defaults_keep_an_explicit_video_duration() -> None:
    filled = apply_sandbox_generation_defaults(
        Operation.TEXT_TO_VIDEO, {"prompt": "香港街道", "duration_seconds": 6}
    )
    assert filled["duration_seconds"] == 6


def test_sandbox_prepare_rejects_an_illegal_h3_duration() -> None:
    with pytest.raises(ValueError, match="4-15"):
        prepare_sandbox_generation_params(
            Operation.TEXT_TO_VIDEO,
            {
                "prompt": "香港街道",
                "duration_seconds": 16,
                "video_options": {"resolution": "2K"},
            },
        )
