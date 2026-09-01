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
from app.models.enums import CharacterViewAngle, ImageAssetKind, Operation, QualityTier


def _request(operation: str, **param_overrides: object) -> GenerationJobCreateRequest:
    params = GenerationParams(prompt="测试提示词", **param_overrides)
    return GenerationJobCreateRequest(
        operation=operation, quality_tier=QualityTier.STANDARD, params=params
    )


def test_image_to_image_does_not_require_a_reference_image() -> None:
    """The prompt is mandatory either way; a reference image is only optional
    extra context that rides along with it — see
    `workflow_templates_service.canonical_operation`. `image_to_image` and
    `text_to_image` share one workflow graph, distinguished only by whether
    the requester happened to attach a reference."""
    bare = _request(Operation.IMAGE_TO_IMAGE)
    assert bare.operation == Operation.IMAGE_TO_IMAGE
    assert bare.params.reference_asset_ids == []

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

    with pytest.raises(ValidationError, match="2-15"):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=16,
            video_options={"resolution": "2K"},
        )


def test_video_options_accept_the_widened_aspect_ratio_and_resolution_set() -> None:
    """`adaptive` joined the legal aspect-ratio set alongside H3's original
    six, and `resolution` accepts any of the four clarity tiers — not just
    H3's own `2K` — since it now names a tier, not a vendor's literal
    spelling (see `VideoGenerationOptions.resolution`)."""
    adaptive = _request(
        Operation.TEXT_TO_VIDEO,
        duration_seconds=5,
        aspect_ratio="adaptive",
        video_options={"resolution": "720p", "reference_mode": "input_references"},
    )
    assert adaptive.params.aspect_ratio == "adaptive"
    assert adaptive.params.video_options is not None
    assert adaptive.params.video_options.resolution == "720p"


def test_video_options_reject_a_raw_vendor_resolution_spelling() -> None:
    """`resolution` is a client-facing tier token, not a vendor's own
    literal — `"768P"` (MiniMax H3's spelling, now a `"720p"`-tier synonym
    resolved server-side by `app.providers.base.resolve_resolution_tier`)
    and `"480P"` (a hypothetical future capital-P model) must both be
    rejected here, the same as any other value outside the four tiers."""
    with pytest.raises(ValidationError):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=5,
            video_options={"resolution": "768P"},
        )
    with pytest.raises(ValidationError):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=5,
            video_options={"resolution": "480P"},
        )


def test_video_options_reject_an_aspect_ratio_outside_the_documented_set() -> None:
    with pytest.raises(ValidationError, match="画幅必须为"):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=5,
            aspect_ratio="7:3",
            video_options={"resolution": "2K"},
        )


def test_video_options_reject_a_resolution_outside_2k_and_768p() -> None:
    with pytest.raises(ValidationError):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=5,
            video_options={"resolution": "4K"},
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


def test_asset_kind_is_accepted_for_text_to_image_and_image_to_image() -> None:
    request = _request(Operation.TEXT_TO_IMAGE, asset_kind=ImageAssetKind.CHARACTER.value)
    assert request.params.asset_kind == ImageAssetKind.CHARACTER

    request = _request(
        Operation.IMAGE_TO_IMAGE,
        reference_asset_ids=["asset-1"],
        asset_kind=ImageAssetKind.SCENE.value,
    )
    assert request.params.asset_kind == ImageAssetKind.SCENE


def test_asset_kind_defaults_to_general() -> None:
    request = _request(Operation.TEXT_TO_IMAGE)
    assert request.params.asset_kind == ImageAssetKind.GENERAL


def test_general_asset_kind_is_accepted_for_every_operation() -> None:
    """`GENERAL` is the default/no-op value, so it must not trip the
    image-only restriction even for a non-image operation."""
    request = _request(Operation.TEXT_TO_VIDEO, duration_seconds=5, asset_kind="general")
    assert request.params.asset_kind == ImageAssetKind.GENERAL


def test_a_non_general_asset_kind_is_rejected_for_a_non_image_operation() -> None:
    with pytest.raises(ValidationError, match="asset_kind 仅适用于文生图/图生图"):
        _request(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=5,
            asset_kind=ImageAssetKind.CHARACTER.value,
        )


def test_target_character_and_scene_ids_round_trip() -> None:
    request = _request(
        Operation.TEXT_TO_IMAGE,
        asset_kind=ImageAssetKind.CHARACTER.value,
        character_views=[CharacterViewAngle.SIDE.value],
        target_character_id="sk_existing_character",
    )
    assert request.params.target_character_id == "sk_existing_character"
    assert request.params.target_scene_id is None
    assert request.params.character_views == [CharacterViewAngle.SIDE]


def test_validate_generation_params_rejects_a_zero_video_duration() -> None:
    with pytest.raises(ValueError, match="视频生成必须指定时长"):
        validate_generation_params(Operation.TEXT_TO_VIDEO, duration_seconds=0)


def test_validate_generation_params_rejects_h3_duration_out_of_range() -> None:
    with pytest.raises(ValueError, match="2-15"):
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


def test_video_analysis_allows_an_empty_prompt_with_one_reference() -> None:
    """`prompt` means "optional extra notes on the clip" for this operation,
    unlike every other operation where it is the mandatory instruction."""
    request = GenerationJobCreateRequest(
        operation=Operation.VIDEO_ANALYSIS,
        quality_tier=QualityTier.STANDARD,
        params=GenerationParams(reference_asset_ids=["asset-video"]),
    )
    assert request.params.prompt == ""
    assert request.params.reference_asset_ids == ["asset-video"]


def test_video_analysis_requires_exactly_one_reference_video() -> None:
    with pytest.raises(ValidationError, match="必须提供且仅提供一段"):
        GenerationJobCreateRequest(
            operation=Operation.VIDEO_ANALYSIS,
            quality_tier=QualityTier.STANDARD,
            params=GenerationParams(),
        )

    with pytest.raises(ValidationError, match="必须提供且仅提供一段"):
        GenerationJobCreateRequest(
            operation=Operation.VIDEO_ANALYSIS,
            quality_tier=QualityTier.STANDARD,
            params=GenerationParams(reference_asset_ids=["asset-1", "asset-2"]),
        )


def test_every_other_operation_still_requires_a_non_empty_prompt() -> None:
    with pytest.raises(ValidationError, match="必须填写提示词"):
        GenerationJobCreateRequest(
            operation=Operation.TEXT_TO_IMAGE,
            quality_tier=QualityTier.STANDARD,
            params=GenerationParams(prompt="   "),
        )


def test_video_to_video_requires_a_reference_unless_a_licensed_source_is_attached() -> None:
    with pytest.raises(ValidationError, match="必须提供参考视频"):
        _request(Operation.VIDEO_TO_VIDEO, duration_seconds=8, video_options={"reference_mode": "input_references"})

    uploaded = _request(
        Operation.VIDEO_TO_VIDEO,
        duration_seconds=8,
        reference_asset_ids=["ast_uploaded"],
        video_options={"reference_mode": "input_references"},
    )
    assert uploaded.params.reference_asset_ids == ["ast_uploaded"]

    licensed = GenerationJobCreateRequest(
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        source_work_id="wrk_licensed",
        params=GenerationParams(
            prompt="改成暴雨",
            duration_seconds=8,
            video_options=VideoGenerationOptions(reference_mode="input_references"),
        ),
    )
    assert licensed.params.reference_asset_ids == []
    assert licensed.source_work_id == "wrk_licensed"


def test_sandbox_prepare_rejects_an_illegal_h3_duration() -> None:
    with pytest.raises(ValueError, match="2-15"):
        prepare_sandbox_generation_params(
            Operation.TEXT_TO_VIDEO,
            {
                "prompt": "香港街道",
                "duration_seconds": 16,
                "video_options": {"resolution": "2K"},
            },
        )


def test_forced_model_is_accepted_for_image_and_video_creation() -> None:
    image_request = _request(Operation.TEXT_TO_IMAGE, forced_model="doubao-seedream-5-0-pro")
    assert image_request.params.forced_model == "doubao-seedream-5-0-pro"

    video_request = _request(
        Operation.TEXT_TO_VIDEO, duration_seconds=5, forced_model="minimax-h3"
    )
    assert video_request.params.forced_model == "minimax-h3"


def test_forced_model_is_rejected_outside_image_and_video_creation() -> None:
    with pytest.raises(ValidationError, match="forced_model 仅适用于图片创作/视频创作"):
        _request(Operation.AUDIO_GENERATION, extra={"voice": "nova"}, forced_model="tts-model")

    with pytest.raises(ValidationError, match="forced_model 仅适用于图片创作/视频创作"):
        GenerationJobCreateRequest(
            operation=Operation.VIDEO_ANALYSIS,
            quality_tier=QualityTier.STANDARD,
            params=GenerationParams(
                reference_asset_ids=["asset-video"], forced_model="some-model"
            ),
        )


def test_forced_model_defaults_to_unset() -> None:
    request = _request(Operation.TEXT_TO_IMAGE)
    assert request.params.forced_model is None


def test_generation_prompt_accepts_4096_and_rejects_4097() -> None:
    accepted = GenerationParams(prompt="测" * 4096)
    assert len(accepted.prompt) == 4096

    with pytest.raises(ValidationError):
        GenerationParams(prompt="测" * 4097)
