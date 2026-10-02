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


def test_audio_generation_requires_a_voice_or_a_clone_reference() -> None:
    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION)

    with pytest.raises(ValidationError, match="音频生成必须指定音色"):
        _request(Operation.AUDIO_GENERATION, extra={"voice": "   "})

    # The voice id is no longer a fixed enum — DMXAPI's `tts-pro` and
    # AiHubMix's Gemini voices both bring their own vendor-specific ids, so
    # any non-empty string is accepted at this schema layer; the provider
    # itself rejects one it doesn't recognise.
    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "not-a-real-voice"})
    assert request.operation == Operation.AUDIO_GENERATION

    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "nova"})
    assert request.operation == Operation.AUDIO_GENERATION

    # A voice-clone reference sample stands in for a named voice.
    request = _request(Operation.AUDIO_GENERATION, reference_asset_ids=["ast_voice1"])
    assert request.operation == Operation.AUDIO_GENERATION


def test_audio_generation_clone_reference_is_capped_at_one() -> None:
    with pytest.raises(ValidationError, match="最多只能提供 1 段声音克隆参考音频"):
        _request(Operation.AUDIO_GENERATION, reference_asset_ids=["ast_voice1", "ast_voice2"])


def test_audio_generation_does_not_require_a_duration() -> None:
    """Unlike the video operations, a zero duration is fine here."""
    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "alloy"}, duration_seconds=0)
    assert request.params.duration_seconds == 0


def test_music_generation_requires_an_audio_style() -> None:
    with pytest.raises(ValidationError, match="必须指定 audio_style"):
        _request(Operation.MUSIC_GENERATION)

    with pytest.raises(ValidationError, match="必须指定 audio_style"):
        _request(Operation.MUSIC_GENERATION, extra={"audio_style": "bgm"})

    music = _request(Operation.MUSIC_GENERATION, extra={"audio_style": "music"})
    assert music.operation == Operation.MUSIC_GENERATION

    sfx = _request(Operation.MUSIC_GENERATION, extra={"audio_style": "sfx"})
    assert sfx.operation == Operation.MUSIC_GENERATION


def test_music_generation_rejects_any_reference_asset() -> None:
    with pytest.raises(ValidationError, match="不支持参考素材"):
        _request(
            Operation.MUSIC_GENERATION,
            extra={"audio_style": "music"},
            reference_asset_ids=["ast_ref1"],
        )


def test_music_generation_does_not_require_a_duration() -> None:
    request = _request(
        Operation.MUSIC_GENERATION, extra={"audio_style": "music"}, duration_seconds=0
    )
    assert request.params.duration_seconds == 0


def test_music_generation_sfx_duration_is_bounded_when_provided() -> None:
    with pytest.raises(ValidationError, match="音效时长必须为"):
        _request(
            Operation.MUSIC_GENERATION,
            extra={"audio_style": "sfx"},
            duration_seconds=25,
        )

    request = _request(
        Operation.MUSIC_GENERATION,
        extra={"audio_style": "sfx"},
        duration_seconds=10,
    )
    assert request.params.duration_seconds == 10

    # Music (not SFX) never takes a duration control — an out-of-SFX-range
    # value is simply ignored by the adapted models, not rejected here.
    request = _request(
        Operation.MUSIC_GENERATION,
        extra={"audio_style": "music"},
        duration_seconds=25,
    )
    assert request.params.duration_seconds == 25


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

    with pytest.raises(ValidationError, match="首尾帧不能与普通参考素材同时使用"):
        _request(
            Operation.IMAGE_TO_VIDEO,
            duration_seconds=5,
            reference_asset_ids=["asset-reference"],
            video_options={
                "reference_mode": "frame_images",
                "first_frame_asset_id": "asset-first",
            },
        )

    with pytest.raises(ValidationError, match="首尾帧不能与角色参考、场景参考同时使用"):
        _request(
            Operation.IMAGE_TO_VIDEO,
            duration_seconds=5,
            character_ids=["sk-char"],
            scene_ids=["sk-scene"],
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
        _request(
            Operation.VIDEO_TO_VIDEO,
            duration_seconds=8,
            video_options={"reference_mode": "input_references"},
        )

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

    video_request = _request(Operation.TEXT_TO_VIDEO, duration_seconds=5, forced_model="minimax-h3")
    assert video_request.params.forced_model == "minimax-h3"


def test_forced_model_is_accepted_for_audio_generation() -> None:
    """Unlike image/video, `audio_generation` has no per-model studio
    `resolutions` tier — the C-end voice picker (`app.providers.
    model_catalog.voices_for_model`) is what actually needs to know which
    model was picked, hence this operation joining the `forced_model`
    scope alongside image/video."""
    request = _request(Operation.AUDIO_GENERATION, extra={"voice": "nova"}, forced_model="tts-1")
    assert request.params.forced_model == "tts-1"


def test_forced_model_is_rejected_outside_image_video_or_audio_creation() -> None:
    with pytest.raises(ValidationError, match="forced_model 仅适用于图片创作/视频创作/音频创作"):
        GenerationJobCreateRequest(
            operation=Operation.VIDEO_ANALYSIS,
            quality_tier=QualityTier.STANDARD,
            params=GenerationParams(reference_asset_ids=["asset-video"], forced_model="some-model"),
        )


def test_forced_model_defaults_to_unset() -> None:
    request = _request(Operation.TEXT_TO_IMAGE)
    assert request.params.forced_model is None


def test_generation_prompt_accepts_4096_and_rejects_4097() -> None:
    accepted = GenerationParams(prompt="测" * 4096)
    assert len(accepted.prompt) == 4096

    with pytest.raises(ValidationError):
        GenerationParams(prompt="测" * 4097)


# ---- character/scene presets (`_asset_presets_scoped_to_their_kind`) ----


def test_character_expressions_are_accepted_on_a_character_job() -> None:
    params = GenerationParams(
        prompt="林夏",
        asset_kind=ImageAssetKind.CHARACTER,
        character_expressions=["smile", "smirk", "breakdown"],
    )
    assert params.character_expressions == ["smile", "smirk", "breakdown"]
    assert params.character_views == [CharacterViewAngle.FRONT]


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_kind": ImageAssetKind.SCENE, "character_expressions": ["smile"]},
        {"asset_kind": ImageAssetKind.GENERAL, "character_outfit_label": "婚礼"},
        {
            "asset_kind": ImageAssetKind.CHARACTER,
            "character_expressions": ["smile"],
            "character_outfit_label": "婚礼",
        },
        {
            "asset_kind": ImageAssetKind.CHARACTER,
            "character_expressions": ["smile"],
            "character_views": ["side", "back"],
        },
        {"asset_kind": ImageAssetKind.CHARACTER, "character_expressions": ["grumpy"]},
        {"asset_kind": ImageAssetKind.CHARACTER, "character_expressions": ["smile"] * 10},
        {"asset_kind": ImageAssetKind.CHARACTER, "scene_lighting": "dusk"},
        {"asset_kind": ImageAssetKind.SCENE, "scene_lighting": "noon"},
        {
            "asset_kind": ImageAssetKind.SCENE,
            "scene_lighting": "dusk",
            "scene_variants": [{"lighting": "day"}, {"lighting": "dusk"}],
        },
        {"asset_kind": ImageAssetKind.SCENE, "scene_variants": [{"lighting": "day"}]},
        {"asset_kind": ImageAssetKind.SCENE, "scene_variants": [{"lighting": "day"}, {}]},
        {
            "asset_kind": ImageAssetKind.SCENE,
            "scene_variants": [{"lighting": "day"}] * 5,
        },
        {
            "character_ids": ["chr_a"],
            "character_ref_selection": [{"character_id": "chr_b", "asset_ids": ["ast_1"]}],
        },
        {
            "character_ids": ["chr_a"],
            "character_ref_selection": [{"character_id": "chr_a", "asset_ids": []}],
        },
    ],
)
def test_presets_outside_their_asset_kind_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        GenerationParams(prompt="测试", **overrides)


def test_scene_presets_and_variant_groups_are_accepted_on_a_scene_job() -> None:
    single = GenerationParams(
        prompt="客厅",
        asset_kind=ImageAssetKind.SCENE,
        scene_lighting="night_interior",
        scene_weather="rain",
        scene_state="damage_medium",
        scene_period="republic",
    )
    assert single.scene_period == "republic"
    group = GenerationParams(
        prompt="客厅",
        asset_kind=ImageAssetKind.SCENE,
        scene_variants=[{"lighting": "day"}, {"lighting": "dusk", "weather": "rain"}],
    )
    assert group.scene_variants is not None and len(group.scene_variants) == 2


def test_character_ref_selection_must_name_a_selected_character() -> None:
    params = GenerationParams(
        prompt="测试",
        character_ids=["chr_a"],
        character_ref_selection=[{"character_id": "chr_a", "asset_ids": ["ast_1", "ast_2"]}],
    )
    assert params.character_ref_selection is not None
    assert params.character_ref_selection[0].asset_ids == ["ast_1", "ast_2"]
