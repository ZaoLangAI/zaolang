"""Generation, upload, credit and notification payloads."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from app.api.schemas.common import ApiModel
from app.domain.image_assets.vocabulary import (
    MAX_CHARACTER_EXPRESSIONS,
    MAX_OUTFIT_LABEL_LEN,
    MAX_SCENE_VARIANTS,
    MIN_SCENE_VARIANTS,
    CharacterExpression,
    SceneLighting,
    ScenePeriod,
    SceneState,
    SceneWeather,
)
from app.models.enums import (
    CHARACTER_JOB_VIEWS,
    CharacterViewAngle,
    ImageAssetKind,
    JobStatus,
    LedgerEntryType,
    MediaType,
    NotificationType,
    Operation,
    QualityTier,
    ReportReason,
    VideoAssetKind,
)
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

IMAGE_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
)

# `audio_generation`'s voice id is deliberately *not* a fixed enum here any
# more — once DMXAPI's `tts-pro` (dozens of Chinese emotional voices) and
# AiHubMix's Gemini voices are both reachable through the same operation,
# the legal set is "whichever voice ids the chosen model/provider actually
# has", which only the studio's per-model picker knows. This schema only
# checks the shape (non-empty, bounded length) — see `validate_generation_
# params`'s `AUDIO_GENERATION` branch below. A provider that gets a voice id
# it doesn't recognize fails the call itself; that is not this schema's job
# to pre-empt.
AUDIO_VOICE_MAX_LENGTH = 60
# At most one reference asset for `audio_generation`: the voice-clone sample
# (`MediaType.AUDIO`, see `media.service.validate_generation_references`) —
# never more than one, since a clone call takes exactly one reference voice.
AUDIO_CLONE_MAX_REFERENCES = 1
# `music_generation`'s `extra.audio_style` sub-mode switch — see
# `Operation.MUSIC_GENERATION`'s own docstring in `app.models.enums` for why
# this is a second sub-mode field rather than a third operation.
MUSIC_STYLES = frozenset({"music", "sfx"})
# ElevenLabs Sound Effects V2 (`fal_media.py::FAL_SFX_MODEL`) is the one
# adapted music/SFX model that takes an explicit, billable duration
# (0.5-22s per its own docs) — MiniMax Music 2.6 and DMXAPI's music-3.0 take
# none. `duration_seconds` is optional for `audio_style="sfx"`: 0 (the
# `GenerationParams` default) means "let the model decide", same convention
# `apply_sandbox_generation_defaults` uses for a video's own duration. Only
# enforced when a caller actually sets one, so a client that never learned
# about this window still gets a working default-length effect.
MUSIC_SFX_MIN_DURATION_SECONDS = 1
MUSIC_SFX_MAX_DURATION_SECONDS = 22
VIDEO_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
)
# Mirrored from `app.providers.aihubmix_media`'s `_NATIVE_VIDEO_PROFILES` so
# the C-end schema does not import a provider module. Keep the two in step.
#
# This is an upfront *ceiling*, not a per-model contract: it's the union
# across every registered native-video profile (today MiniMax H3's 4–15s/ten
# aspect ratios and wan2.7-videoedit's narrower 2–10s/five aspect ratios),
# wide enough that neither profile's legal values get wrongly rejected here.
# Fine-grained per-model legality is enforced later, per routing candidate,
# by `router._request_constraint_failure` (duration/aspect/reference-mode
# still eliminate; resolution is adapted downward on the final model).
VIDEO_MIN_DURATION_SECONDS = 2
VIDEO_MAX_DURATION_SECONDS = 15
VIDEO_ASPECT_RATIOS: frozenset[str] = frozenset(
    {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "3:2", "2:3", "9:21", "adaptive"}
)
# Same default the C-end studio ships (`generation-studio.tsx`); a prompt-only
# sandbox try-it must land inside the shared 2–15s window or route_score
# filters out every video provider as `duration_below_provider_minimum`.
DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS = 8


def _frame_images_conflict_message(
    references: Sequence[str],
    characters: Sequence[str],
    scenes: Sequence[str],
) -> str:
    """Names only the reference kinds that actually collided with first/last frames."""
    conflicts: list[str] = []
    if references:
        conflicts.append("普通参考素材")
    if characters:
        conflicts.append("角色参考")
    if scenes:
        conflicts.append("场景参考")
    joined = "、".join(conflicts)
    return f"首尾帧不能与{joined}同时使用。请取消首尾帧，或改回图片/视频参考。"


class VideoGenerationOptions(ApiModel):
    """Typed native-video options; arbitrary provider JSON and webhooks are
    forbidden. `resolution` is a clarity *tier* the client picks — not any
    one vendor's own spelling. `app.providers.base.RESOLUTION_TIER_MEMBERS`
    is the single source of truth mapping each tier to the vendor literals
    it covers (e.g. `"720p"` covers MiniMax H3's own `"768P"` token too, so
    picking it lets H3 and the lowercase-`p` models — `doubao-seedance-2-5
    -260628`, `wan2.7-videoedit` — actually compete for the same request
    instead of being mutually invisible over a spelling difference).
    `app.providers.base.adapt_resolution_tier` is where a tier becomes a
    ceiling on the *final* model: exact match if that candidate has it,
    otherwise the highest strictly lower supported tier (never a raise to
    2K from 1080p), and only as a last resort the model's lowest tier so
    the job still runs. Costing and `execute_provider_generate` both send
    the adapted vendor literal. This schema never sees a vendor's raw
    spelling. A candidate whose `resolutions` map to no studio tier at all
    is the only remaining `resolution_not_supported` hard filter."""

    # Omitted on a video remix so the router does not default-filter
    # cheaper video-edit models whose vendor spelling isn't in this tier.
    # Create/new still sends one of the four tiers below explicitly.
    resolution: Literal["480p", "720p", "1080p", "2K"] | None = None
    reference_mode: Literal["input_references", "frame_images"] = "input_references"
    first_frame_asset_id: str | None = Field(default=None, max_length=40)
    last_frame_asset_id: str | None = Field(default=None, max_length=40)
    # `motion_guide`: the one video among `reference_asset_ids` is a 白膜
    # blockout render — camera, blocking and timing to follow, not footage
    # to reproduce. Routes only to reference-to-video models and prepends a
    # fixed directive (`app.domain.media.reference_roles`). `None` keeps a
    # video reference's ordinary meaning.
    reference_video_role: Literal["motion_guide"] | None = None


def apply_sandbox_generation_defaults(
    operation: Operation, params: dict[str, Any]
) -> dict[str, Any]:
    """Fills a video duration so a prompt-only sandbox try-it is routable.

    C-end submit already requires `duration_seconds > 0`. The sandbox dialog
    historically did not, so the only catalog entry (MiniMax H3, at the time)
    hard-filtered as `duration_below_provider_minimum` and the job failed with
    "暂时没有可用的生成路线". Explicit zero / omitted duration becomes 8
    seconds — the same default the C-end studio uses, inside every registered
    native-video profile's window.
    """
    if operation not in VIDEO_OPERATIONS:
        return params
    raw = params.get("duration_seconds")
    if raw is None or raw == "" or raw == 0:
        return {**params, "duration_seconds": DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS}
    return params


def validate_generation_params(
    operation: Operation,
    *,
    duration_seconds: int = 0,
    aspect_ratio: str = "16:9",
    reference_asset_ids: Sequence[str] | None = None,
    character_ids: Sequence[str] | None = None,
    scene_ids: Sequence[str] | None = None,
    video_options: VideoGenerationOptions | None = None,
    asset_kind: ImageAssetKind | None = None,
    video_asset_kind: VideoAssetKind | None = None,
    forced_model: str | None = None,
    extra: Mapping[str, Any] | None = None,
    licensed_source: bool = False,
) -> None:
    """Shared C-end / sandbox rules. Raises `ValueError` on illegal combinations.

    `licensed_source` is true when the request already carries a remix
    `source_work_id` — `jobs_service.submit` injects that version's primary
    output before references are ownership-checked, so an empty client list
    is still a legal `video_to_video` shape.
    """
    references = list(reference_asset_ids or [])
    characters = list(character_ids or [])
    scenes = list(scene_ids or [])
    extras = extra or {}
    if (
        asset_kind is not None
        and asset_kind != ImageAssetKind.GENERAL
        and operation not in IMAGE_OPERATIONS
    ):
        raise ValueError("asset_kind 仅适用于文生图/图生图。")
    if (
        video_asset_kind is not None
        and video_asset_kind != VideoAssetKind.GENERAL
        and operation not in VIDEO_OPERATIONS
    ):
        raise ValueError("video_asset_kind 仅适用于视频生成。")
    if forced_model and operation not in IMAGE_OPERATIONS | VIDEO_OPERATIONS | {
        Operation.AUDIO_GENERATION
    }:
        raise ValueError("forced_model 仅适用于图片创作/视频创作/音频创作。")
    if operation in VIDEO_OPERATIONS and duration_seconds <= 0:
        raise ValueError("视频生成必须指定时长。")
    if operation not in VIDEO_OPERATIONS and video_options is not None:
        raise ValueError("video_options 仅适用于视频生成。")
    if video_options is not None:
        if not VIDEO_MIN_DURATION_SECONDS <= duration_seconds <= VIDEO_MAX_DURATION_SECONDS:
            raise ValueError(
                f"视频时长必须为 {VIDEO_MIN_DURATION_SECONDS}-{VIDEO_MAX_DURATION_SECONDS} 秒。"
            )
        if aspect_ratio not in VIDEO_ASPECT_RATIOS:
            raise ValueError(f"画幅必须为: {sorted(VIDEO_ASPECT_RATIOS)}。")
        if video_options.reference_mode == "frame_images":
            if not video_options.first_frame_asset_id:
                raise ValueError("首尾帧模式必须提供首帧图片。")
            if references or characters or scenes:
                raise ValueError(_frame_images_conflict_message(references, characters, scenes))
            if operation != Operation.IMAGE_TO_VIDEO:
                raise ValueError("首尾帧模式必须使用 image_to_video 操作。")
        elif video_options.first_frame_asset_id or video_options.last_frame_asset_id:
            raise ValueError("普通参考素材模式不能传入首帧或尾帧。")
        if video_options.reference_video_role == "motion_guide":
            if video_options.reference_mode != "input_references":
                raise ValueError("白膜参考视频不能与首尾帧同时使用。")
            if operation != Operation.TEXT_TO_VIDEO:
                raise ValueError("白膜参考视频仅适用于 text_to_video。")
            if not references:
                raise ValueError("白膜参考视频模式必须提供参考视频。")
    has_frame_input = bool(video_options and video_options.first_frame_asset_id)
    if operation == Operation.IMAGE_TO_VIDEO and not references and not has_frame_input:
        raise ValueError("图生视频必须提供参考图。")
    if operation == Operation.VIDEO_TO_VIDEO and not references and not licensed_source:
        raise ValueError("视频转视频必须提供参考视频。")
    # `image_to_image` does NOT require a reference — the prompt is what's
    # mandatory; an attached image is optional extra context that rides
    # along with it (see `workflow_templates_service.canonical_operation`).
    # Whether the client calls this `text_to_image` or `image_to_image` is a
    # runtime detail, not a different validation regime.
    if operation == Operation.AUDIO_GENERATION:
        if len(references) > AUDIO_CLONE_MAX_REFERENCES:
            raise ValueError("音频生成最多只能提供 1 段声音克隆参考音频。")
        voice = extras.get("voice")
        has_valid_voice = (
            isinstance(voice, str) and 0 < len(voice.strip()) <= AUDIO_VOICE_MAX_LENGTH
        )
        # A clone reference stands in for a named voice — the reference audio
        # itself carries the identity, so `voice` becomes optional once one
        # is attached (some clone models still take an optional style/voice
        # hint alongside it, but never require it).
        if not has_valid_voice and not references:
            raise ValueError("音频生成必须指定音色，或提供声音克隆参考音频。")
    if operation == Operation.MUSIC_GENERATION:
        # No reference asset of any kind — v1 is a plain text-to-music/SFX
        # call (`media.service.validate_generation_references` enforces the
        # media-type-agnostic half of this rejection once one is attached;
        # this is the shape check that runs before that ownership lookup).
        if references:
            raise ValueError("音乐/音效生成不支持参考素材。")
        audio_style = extras.get("audio_style")
        if audio_style not in MUSIC_STYLES:
            raise ValueError("音乐生成必须指定 audio_style：music 或 sfx。")
        if (
            audio_style == "sfx"
            and duration_seconds
            and not (
                MUSIC_SFX_MIN_DURATION_SECONDS <= duration_seconds <= MUSIC_SFX_MAX_DURATION_SECONDS
            )
        ):
            raise ValueError(
                f"音效时长必须为 {MUSIC_SFX_MIN_DURATION_SECONDS}-"
                f"{MUSIC_SFX_MAX_DURATION_SECONDS} 秒。"
            )
    if operation == Operation.VIDEO_ANALYSIS and len(references) != 1:
        raise ValueError("视频解析必须提供且仅提供一段待解析的参考视频。")


def prepare_sandbox_generation_params(
    operation: Operation, params: dict[str, Any]
) -> dict[str, Any]:
    """Applies sandbox defaults then the shared generation-param rules.

    Raises `ValueError` with a user-facing message; the sandbox route turns
    that into `ValidationFailed` so a bad duration never reaches Celery.
    Extra keys on the free-form sandbox `params` dict are left untouched —
    they must not be forced through `GenerationParams` (`extra=forbid`).
    """
    prepared = apply_sandbox_generation_defaults(operation, params)
    if operation not in VIDEO_OPERATIONS:
        return prepared
    options_raw = prepared.get("video_options")
    try:
        options = (
            None if options_raw is None else VideoGenerationOptions.model_validate(options_raw)
        )
        duration = int(prepared.get("duration_seconds") or 0)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            first = exc.errors()[0]
            message = str(first.get("msg") or exc).removeprefix("Value error, ")
            raise ValueError(message) from exc
        raise ValueError("视频时长必须是整数秒。") from exc
    validate_generation_params(
        operation,
        duration_seconds=duration,
        aspect_ratio=str(prepared.get("aspect_ratio") or "16:9"),
        reference_asset_ids=list(prepared.get("reference_asset_ids") or []),
        character_ids=list(prepared.get("character_ids") or []),
        scene_ids=list(prepared.get("scene_ids") or []),
        video_options=options,
        asset_kind=_parsed_asset_kind(prepared.get("asset_kind")),
        video_asset_kind=_parsed_video_asset_kind(prepared.get("video_asset_kind")),
        forced_model=_parsed_forced_model(prepared.get("forced_model")),
        extra=prepared.get("extra") if isinstance(prepared.get("extra"), dict) else {},
    )
    return prepared


def _parsed_asset_kind(raw: Any) -> ImageAssetKind | None:
    if isinstance(raw, ImageAssetKind):
        return raw
    if isinstance(raw, str) and raw in {kind.value for kind in ImageAssetKind}:
        return ImageAssetKind(raw)
    return None


def _parsed_video_asset_kind(raw: Any) -> VideoAssetKind | None:
    if isinstance(raw, VideoAssetKind):
        return raw
    if isinstance(raw, str) and raw in {kind.value for kind in VideoAssetKind}:
        return VideoAssetKind(raw)
    return None


def _parsed_forced_model(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and raw else None


class CharacterRefSelection(ApiModel):
    """Which of one character's images a job should use instead of the card's
    default subset: a look (`variant_id` → that look's default subset, e.g.
    the 婚礼 outfit), exact images (`asset_ids`, each one of the card's own),
    or both (the images must then belong to that look). Resolved by
    `image_assets.reference_resolver`."""

    character_id: str = Field(max_length=40)
    variant_id: str | None = Field(default=None, max_length=40)
    asset_ids: list[str] | None = Field(default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def _names_a_look_or_images(self) -> CharacterRefSelection:
        if not self.variant_id and not self.asset_ids:
            raise ValueError("请选择造型或具体参考图。")
        return self


class SceneRefSelection(ApiModel):
    """Scene-side twin of `CharacterRefSelection`: a variant (黄昏/战损…),
    exact images, or both."""

    scene_id: str = Field(max_length=40)
    variant_id: str | None = Field(default=None, max_length=40)
    asset_ids: list[str] | None = Field(default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def _names_a_variant_or_images(self) -> SceneRefSelection:
        if not self.variant_id and not self.asset_ids:
            raise ValueError("请选择变体或具体参考图。")
        return self


class ScenePresetCombo(ApiModel):
    """One image of a scene variant group (`GenerationParams.scene_variants`):
    the preset combination that image should show."""

    lighting: SceneLighting | None = None
    weather: SceneWeather | None = None
    state: SceneState | None = None
    period: ScenePeriod | None = None

    @model_validator(mode="after")
    def _at_least_one_axis(self) -> ScenePresetCombo:
        if not (self.lighting or self.weather or self.state or self.period):
            raise ValueError("每个场景变体至少要设置光照/天气/状态/时期中的一项。")
        return self


class ReferenceLabel(ApiModel):
    """What one reference image is — written by the server at submit
    (`media.service.label_references`), never trusted from a client."""

    asset_id: str = Field(max_length=40)
    label: str = Field(max_length=60)


def _check_selection(picked: list[str], allowed: list[str], *, field: str, noun: str) -> None:
    if len(set(picked)) != len(picked):
        raise ValueError(f"{field} 中同一{noun}只能出现一次。")
    if any(item not in allowed for item in picked):
        raise ValueError(f"{field} 中的{noun}必须同时被选中。")


class GenerationParams(ApiModel):
    # No `min_length` here: enforced instead by `validate_generation_params`,
    # which exempts `video_analysis` (this field means "optional extra notes
    # on the uploaded clip" there, not a required creative instruction).
    prompt: str = Field(default="", max_length=4096)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    # `adaptive` is the one non-`W:H` literal — H3's own "let the render
    # decide" aspect ratio (`VIDEO_ASPECT_RATIOS`, below) — so the pattern
    # must accept it explicitly rather than only ever matching a ratio.
    aspect_ratio: str = Field(default="16:9", pattern=r"^(\d{1,2}:\d{1,2}|adaptive)$")
    duration_seconds: int = Field(default=0, ge=0, le=MAX_GENERATION_DURATION_SECONDS)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=9)
    video_options: VideoGenerationOptions | None = None
    style_preset_id: str | None = None
    # Names a `shortform.profiles` entry. Absent for ordinary generation, which
    # is why every downstream check treats it as optional.
    shortform_profile: str | None = Field(default=None, max_length=64)
    # Cast picked from the character library. Their reference images and voice
    # descriptions are merged into `reference_asset_ids` / `extra` in
    # `characters.service.apply_character_refs` before the job is priced.
    character_ids: list[str] = Field(default_factory=list, max_length=4)
    # Settings picked from the scene library. Their reference stills/clips are
    # merged into `reference_asset_ids` in `scenes.service.apply_scene_refs`,
    # sharing the same 9-slot budget with `character_ids`' references above.
    scene_ids: list[str] = Field(default_factory=list, max_length=4)
    # Which `CreationSkill`s (if any) the client applied to this request, in
    # pick order. Not trusted blindly: the `skill_context` workflow node
    # re-fetches and re-merges each skill's own params server-side before
    # generation runs.
    skill_ids: list[str] = Field(default_factory=list, max_length=5)
    # Platform-curated style catalogue entry. Single and mutually exclusive —
    # unlike `skill_ids`. The same `skill_context` node re-fetches it so a
    # bare API client that never merged locally still gets `prompt_suffix`.
    style_gallery_id: str | None = Field(default=None, max_length=40)
    # What a `text_to_image`/`image_to_image` output is *for* — orthogonal to
    # `operation`. Selects both which `GenerationWorkflowTemplate` runs
    # (`workflow_templates_service.get_active`) and, for `CHARACTER`/`SCENE`,
    # which asset the successful output(s) auto-attach to
    # (`app.workflows.nodes.execute_asset_output_link`). Meaningless (and
    # rejected — see `validate_generation_params`) for any other operation.
    asset_kind: ImageAssetKind = ImageAssetKind.GENERAL
    # Only meaningful when `asset_kind == CHARACTER`: which of front/side/back
    # this job produces, one at a time (`app.workflows.nodes
    # .execute_asset_output_advance` loops the shared graph back to
    # `asset_planning` between each). Defaults to `["front"]` when omitted —
    # a plain single-view request. A "补全侧面/背面" completion request names
    # `["side", "back"]` explicitly, producing both from one job.
    character_views: list[CharacterViewAngle] | None = Field(default=None, max_length=3)
    # The character skill / scene to auto-attach this job's output(s) to, for
    # `asset_kind == CHARACTER` / `== SCENE` respectively. Left unset, a
    # `CHARACTER` job creates a brand-new character skill named after the
    # plan's subject instead of updating an existing one.
    target_character_id: str | None = Field(default=None, max_length=40)
    target_scene_id: str | None = Field(default=None, max_length=40)
    # Overrides the planner's own guessed `subject_name` when auto-creating a
    # new character/scene skill (no `target_character_id`/`target_scene_id`).
    # Only meaningful for a caller that already knows the exact name — e.g.
    # the script studio's "生成角色图/场景图" jump-out, which carries the
    # script's own character name/scene heading rather than letting the
    # planner guess one from the prompt. Ignored once a target id is set
    # (there's nothing to name), and ignored for `asset_kind == GENERAL`.
    subject_name_hint: str | None = Field(default=None, max_length=60)
    # Lets the client opt out of `execute_asset_output_link` entirely — e.g.
    # borrowing an existing character's front view for side/back consistency
    # without also writing the new output back into that character's roster.
    # Ignored (treated as `True`) when `asset_kind` is `GENERAL`, since that
    # node is already a no-op in that case. Shared by the video asset-kind
    # path too (`video_asset_kind` below) via the same
    # `execute_asset_output_link` opt-out check.
    auto_attach_asset: bool = True
    # What a `text_to_video`/`image_to_video`/`video_to_video` output is
    # *for* — the video-side equivalent of `asset_kind` above, orthogonal to
    # `operation` the same way. Selects both which `GenerationWorkflowTemplate`
    # runs and, for `CHARACTER_ACTION`, which character the successful output
    # auto-attaches to as a clip (`action_clips`, not `reference_assets` —
    # see `app.workflows.nodes._link_character_action_output`). Deliberately
    # a separate field/enum from `asset_kind` rather than a shared one: video
    # has no `CharacterViewAngle`
    # multi-view loop, and mixing the two into one field would let a video
    # job's kind value collide with an image kind's string in any lookup
    # keyed by bare `asset_kind` string (see `VideoAssetKind`'s docstring).
    # Meaningless (and rejected — see `validate_generation_params`) for any
    # non-video operation.
    video_asset_kind: VideoAssetKind = VideoAssetKind.GENERAL
    # Opts out of `intent_router.select_provider()`'s LLM-driven pick
    # entirely (`app.agents.router.route()`'s `forced_model` branch): the
    # candidate catalogue is still hard-filtered exactly as usual (capability/
    # tier/duration/aspect-ratio/resolution-tier/latency/already-tried), but
    # the winner is whichever surviving candidate's `ProviderCapability
    # .model_or_workflow` matches this string, chosen deterministically
    # (sorted by provider name) rather than by the routing agent. No
    # candidate matching this exact model name is a hard failure
    # (`reason="forced_model_unavailable"`) — there is no silent fallback to
    # the normal LLM-driven route. Only meaningful for image/video creation
    # (see `validate_generation_params`); `None` (the default) is today's
    # unchanged intent-router-driven behavior.
    forced_model: str | None = Field(default=None, max_length=200)
    # `asset_kind=character` only: produce ONE composite image showing the
    # same character with each of these expressions (a grid, or a single
    # close-up for one) instead of the character sheet — see
    # `app.domain.image_assets.prompt_builder`. Needs the character's own
    # sheet as reference image 1 (rejected at submit otherwise).
    character_expressions: list[CharacterExpression] | None = Field(
        default=None, min_length=1, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    # `asset_kind=character` only: names the outfit this sheet shows
    # (日常/婚礼/战甲…). Written into the reference entry's `label`, which
    # is part of the replace-key — a 婚礼 sheet never replaces the 日常 one.
    character_outfit_label: str | None = Field(
        default=None, min_length=1, max_length=MAX_OUTFIT_LABEL_LEN
    )
    # `asset_kind=character` only: produce the card's identity portrait
    # (定妆照: one front-facing head-and-shoulders shot, neutral expression,
    # plain background) instead of a sheet. Filed as `identity_portrait` in
    # the default look; once approved it is the anchor every look's sheet
    # and every video job leads with. Exclusive with expressions/outfit.
    character_portrait: bool = False
    # `asset_kind=character|scene`: the look / scene variant of the target
    # card this job's output is filed under (`asset_output_link`). Unset →
    # the outfit label / the scene presets' variant / the default.
    target_variant_id: str | None = Field(default=None, max_length=40)
    # Per-character pick of which reference images to send (see
    # `CharacterRefSelection`); characters not listed use their default
    # subset. Every `character_id` must also be in `character_ids`.
    character_ref_selection: list[CharacterRefSelection] | None = Field(default=None, max_length=4)
    # Per-scene pick of which reference images to send; same rules as
    # `character_ref_selection` against `scene_ids`.
    scene_ref_selection: list[SceneRefSelection] | None = Field(default=None, max_length=4)
    # `asset_kind=scene` only: one preset per axis for a single scene image.
    scene_lighting: SceneLighting | None = None
    scene_weather: SceneWeather | None = None
    scene_state: SceneState | None = None
    scene_period: ScenePeriod | None = None
    # `asset_kind=scene` only: a variant *group* — one image per entry from a
    # single provider call (models with group output only). Mutually
    # exclusive with the single-image `scene_*` presets above.
    scene_variants: list[ScenePresetCombo] | None = Field(
        default=None, min_length=MIN_SCENE_VARIANTS, max_length=MAX_SCENE_VARIANTS
    )
    # Server-written at submit: what each reference image is, for the
    # prompt's "参考图说明" legend. Any client-sent value is discarded.
    reference_labels: list[ReferenceLabel] | None = Field(default=None, max_length=9)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _asset_presets_scoped_to_their_kind(self) -> GenerationParams:
        is_character = self.asset_kind == ImageAssetKind.CHARACTER
        is_scene = self.asset_kind == ImageAssetKind.SCENE
        if not is_character and (self.character_expressions or self.character_outfit_label):
            raise ValueError("表情与造型名称仅适用于 asset_kind=character。")
        if self.character_expressions and self.character_outfit_label:
            raise ValueError("表情合集图不能同时指定造型名称。")
        if self.character_portrait:
            if not is_character:
                raise ValueError("定妆照仅适用于 asset_kind=character。")
            if self.character_expressions or self.character_outfit_label:
                raise ValueError("定妆照不能同时指定表情或造型名称。")
            if self.character_views not in (None, [CharacterViewAngle.FRONT]):
                raise ValueError("定妆照不能与侧面/背面视角同时生成。")
        if self.target_variant_id and not (is_character or is_scene):
            raise ValueError("target_variant_id 仅适用于 asset_kind=character/scene。")
        if self.target_variant_id and self.character_outfit_label:
            raise ValueError("目标造型与造型名称只能指定一个。")
        if self.target_variant_id and self.scene_variants:
            raise ValueError("场景变体组会按预设各自归档，不能再指定目标变体。")
        if self.character_expressions and self.character_views not in (
            None,
            [CharacterViewAngle.FRONT],
        ):
            raise ValueError("表情合集图不能与侧面/背面视角同时生成。")
        has_scene_preset = bool(
            self.scene_lighting or self.scene_weather or self.scene_state or self.scene_period
        )
        if not is_scene and (has_scene_preset or self.scene_variants):
            raise ValueError("场景光照/天气/状态/时期仅适用于 asset_kind=scene。")
        if has_scene_preset and self.scene_variants:
            raise ValueError("单张场景预设与场景变体组不能同时使用。")
        _check_selection(
            [entry.character_id for entry in self.character_ref_selection or []],
            self.character_ids,
            field="character_ref_selection",
            noun="角色",
        )
        _check_selection(
            [entry.scene_id for entry in self.scene_ref_selection or []],
            self.scene_ids,
            field="scene_ref_selection",
            noun="场景",
        )
        return self

    @model_validator(mode="after")
    def _character_views_scoped_to_character_kind(self) -> GenerationParams:
        if self.asset_kind != ImageAssetKind.CHARACTER:
            if self.character_views:
                raise ValueError("character_views 仅适用于 asset_kind=character。")
            return self
        views = self.character_views or [CharacterViewAngle.FRONT]
        deduped: list[CharacterViewAngle] = []
        for view in views:
            if view == CharacterViewAngle.GENERAL:
                raise ValueError("character_views 只能是 front/side/back。")
            if view not in deduped:
                deduped.append(view)
        # Canonical order regardless of what the caller listed, matching
        # `execute_asset_output_advance`'s own front → side → back walk.
        self.character_views = [view for view in CHARACTER_JOB_VIEWS if view in deduped]
        return self


class QuoteRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    duration_seconds: int = Field(default=0, ge=0, le=MAX_GENERATION_DURATION_SECONDS)
    # Same fields `GenerationParams` carries — optional here so a quote taken
    # before the rest of the form is filled in still prices correctly.
    # `character_views` having more than one entry is what makes a "补全
    # 侧面/背面" completion job cost more than one image (see `pricing.quote`).
    asset_kind: ImageAssetKind = ImageAssetKind.GENERAL
    character_views: list[CharacterViewAngle] | None = Field(default=None, max_length=3)
    # A scene variant group prices one image per entry.
    scene_variants: list[ScenePresetCombo] | None = Field(
        default=None, min_length=MIN_SCENE_VARIANTS, max_length=MAX_SCENE_VARIANTS
    )


class QuoteResponse(ApiModel):
    credits: int
    estimated_seconds: int
    breakdown: dict[str, int]
    available_credits: int
    sufficient: bool


class BatchQuoteItem(QuoteRequest):
    """One line of a batch: `count` identical jobs."""

    count: int = Field(default=1, ge=1, le=500)


class BatchQuoteRequest(ApiModel):
    items: list[BatchQuoteItem] = Field(min_length=1, max_length=50)


class BatchQuoteLine(ApiModel):
    unit_credits: int
    count: int
    credits: int
    estimated_seconds: int


class BatchQuoteResponse(ApiModel):
    """A batch priced line by line with the same `quote_for` a submit uses
    — an exact sum, never a range (see the `zaolang-credits-billing` skill on
    batch quotes)."""

    items: list[BatchQuoteLine]
    total_credits: int
    available_credits: int
    # What the user's own monthly cap still allows; null = no cap.
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool


class GenerationModelOption(ApiModel):
    """One directly-selectable model for `GenerationParams.forced_model`.

    `model` is the exact string to send back as `forced_model` — it must
    equal some enabled candidate's `ProviderCapability.model_or_workflow`
    verbatim, or `route_score` will find nothing to match and the job fails
    with `forced_model_unavailable`. `label` is display-only, best-effort
    from `app.providers.model_catalog`'s curated catalogue; falls back to
    `model` itself when no catalogue entry matches.

    `resolutions` / `default_resolution` are client-facing studio tiers
    (`480p`/`720p`/`1080p`/`2K`), never a vendor spelling such as `768P`.
    `None` on `resolutions` means unrestricted (or a non-video operation).
    The studio keeps the user's pick as a ceiling and only previews the
    adapted tier locally; `request_json.resolution` is not rewritten.

    `voices` (`audio_generation` only) is this model's discrete preset-voice
    roster from `app.providers.model_catalog.voices_for_model` — `None`
    means either a non-audio operation or a clone-only model with no fixed
    roster (the studio's clone tab then takes over instead of a voice
    `Select`).
    """

    model: str
    label: str
    resolutions: list[Literal["480p", "720p", "1080p", "2K"]] | None = None
    default_resolution: Literal["480p", "720p", "1080p", "2K"] | None = None
    voices: list[str] | None = None
    # Separate images one call can return — >1 only for a model that can
    # serve a scene variant group (`GenerationParams.scene_variants`).
    max_outputs_per_call: int = 1


class GenerationModelListResponse(ApiModel):
    models: list[GenerationModelOption] = Field(default_factory=list)


class GenerationJobCreateRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    params: GenerationParams
    draft_id: str | None = None
    source_work_id: str | None = None
    # Client-side ceiling. The job is refused rather than silently trimmed if
    # the quote exceeds it.
    max_credits: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _video_needs_duration(self) -> GenerationJobCreateRequest:
        # Every operation except `video_analysis` treats `prompt` as the
        # mandatory creative instruction; `GenerationParams` itself cannot
        # enforce that with a plain `min_length=1` because it has no idea
        # which operation it is being submitted for (for `video_analysis`
        # the same field is optional "extra notes on the uploaded clip").
        if self.operation != Operation.VIDEO_ANALYSIS and not self.params.prompt.strip():
            raise ValueError("必须填写提示词。")
        validate_generation_params(
            self.operation,
            duration_seconds=self.params.duration_seconds,
            aspect_ratio=self.params.aspect_ratio,
            reference_asset_ids=self.params.reference_asset_ids,
            character_ids=self.params.character_ids,
            scene_ids=self.params.scene_ids,
            video_options=self.params.video_options,
            asset_kind=self.params.asset_kind,
            video_asset_kind=self.params.video_asset_kind,
            forced_model=self.params.forced_model,
            extra=self.params.extra,
            licensed_source=bool(self.source_work_id),
        )
        return self


class JobInputQuestionOption(ApiModel):
    value: str
    label: str


class JobInputQuestionView(ApiModel):
    id: str
    kind: Literal["single_choice", "multi_choice", "free_text"]
    prompt: str
    options: list[JobInputQuestionOption] = Field(default_factory=list)
    required: bool = False


class JobInputRequestResponse(ApiModel):
    """What a planning/`copy_generate` node is waiting on, for the question form."""

    job_id: str
    node_id: str
    questions: list[JobInputQuestionView]
    expires_at: dt.datetime


class JobAnswerItem(ApiModel):
    question_id: str = Field(min_length=1, max_length=64)
    # `str` for `single_choice`/`free_text`, `list[str]` for `multi_choice` —
    # mirrors `ClarifyPanel`'s own answer shape on the frontend.
    value: str | list[str]


class JobAnswerRequest(ApiModel):
    answers: list[JobAnswerItem] = Field(default_factory=list, max_length=20)


class PromoteJobRequest(ApiModel):
    quality_tier: QualityTier
    # Client-side ceiling on the promoted job, same semantics as
    # `GenerationJobCreateRequest.max_credits`.
    max_credits: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _cannot_promote_to_preview(self) -> PromoteJobRequest:
        if self.quality_tier == QualityTier.PREVIEW:
            raise ValueError("升级档位不能仍为 preview。")
        return self


class RouteSummary(ApiModel):
    provider: str
    provider_kind: str
    model_or_workflow: str
    reason: str = ""


class RoutingCandidate(ApiModel):
    """One row of the router's decision trace, kept for replay in the console."""

    provider: str
    eligible: bool
    filter_reason: str | None = None
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    # Micro-USD (1e-6 USD): a typical call's retry-amplified cost, and what
    # this particular request was projected to cost.
    effective_cost_micro_usd: int = 0
    estimated_cost_micro_usd: int = 0
    # Both figures came from a built-in prior, not a configured price.
    cost_is_estimated: bool = False


class JobEventResponse(ApiModel):
    sequence: int
    event_type: str
    status: JobStatus
    progress: int
    message: str
    internal_code: str | None = None
    created_at: dt.datetime
    # Which graph node actually wrote this event (see the
    # `zaolang-generation-jobs` skill on `JobEvent.node_id`). Already carried
    # by the admin stream; exposed here too so
    # a multi-view `CHARACTER` job's client can tell an `asset_planning` re-entry
    # (one per produced view) apart from every other `planning`-type event,
    # without matching on `message` text.
    node_id: str | None = None


class VideoAnalysisShot(ApiModel):
    """One shot of the model's per-shot breakdown of the analysed clip."""

    time_range: str = ""
    camera_movement: str = ""
    scene: str = ""
    subject_action: str = ""
    lighting_mood: str = ""
    transition_in: str = ""


class VideoAnalysisResult(ApiModel):
    """Structured output of a `video_analysis` job.

    Mirrors `_VIDEO_ANALYSIS_INSTRUCTIONS` in `app.providers.aihubmix_media`
    field-for-field — that prompt is what actually shapes the model's JSON,
    this schema only validates/echoes it back to the client.
    """

    summary: str = ""
    # The single ready-to-paste prompt the "用于视频创作" deep link carries
    # into `VideoGenerationStudio`'s prompt box.
    composed_prompt: str = ""
    style_tags: list[str] = Field(default_factory=list)
    pacing: str = ""
    shots: list[VideoAnalysisShot] = Field(default_factory=list)


class GenerationJobResponse(ApiModel):
    id: str
    status: JobStatus
    operation: Operation
    quality_tier: QualityTier
    progress: int = 0
    quoted_credits: int
    reserved_credits: int
    actual_credits: int | None = None
    estimated_seconds: int = 0
    route: RouteSummary | None = None
    output_asset_id: str | None = None
    output_url: str | None = None
    output_media_type: MediaType | None = None
    # Every asset the job produced, in generation order — `output_asset_id`/
    # `output_url` above are always this list's first entry. `None` for the
    # overwhelming majority of jobs that only ever made one asset; more than
    # one only for an `asset_kind=character` job whose `character_views`
    # named more than one view (see `execute_asset_output_advance`).
    output_asset_ids: list[str] | None = None
    output_urls: list[str] | None = None
    # Signed URL for `GenerationParams.reference_asset_ids[0]`, the job's own
    # input rather than its output. `None` for the many operations that never
    # echo it — today only populated for `video_analysis`, so its history list
    # and detail view can replay the source video without a second asset
    # lookup; harmless to leave `None` elsewhere.
    reference_url: str | None = None
    # Echoes `GenerationParams.asset_kind` back so a client can, e.g., offer
    # "save as a shareable cover skill" on a succeeded `cover` job's detail
    # page without having kept the original request around.
    asset_kind: ImageAssetKind | None = None
    # Echoes `GenerationParams.video_asset_kind` back — the video-side
    # equivalent of `asset_kind` above, `None` for every non-video operation.
    video_asset_kind: VideoAssetKind | None = None
    # Echoes `GenerationParams.forced_model` back — `None` means this job let
    # `intent_router.select_provider()` pick, same as today.
    forced_model: str | None = None
    # Echoes `GenerationParams.character_views` back — only meaningful with
    # `asset_kind=character`. Lets a client show upfront how many views this
    # job produces (e.g. "第 2/3 张") without re-deriving it from the event
    # stream, and to label `output_asset_ids`/`output_urls`' entries, which
    # are recorded in the same front → side → back order as this list.
    character_views: list[CharacterViewAngle] | None = None
    # How many images this job was priced for (`jobs.service.
    # requested_output_count`): several for a multi-view character job or a
    # scene variant set, else 1. A succeeded job with fewer
    # `output_asset_ids` was a partial delivery, settled per image.
    requested_outputs: int = 1
    # Echoes `GenerationParams.duration_seconds` back — lets a client re-quote
    # a promoted tier for this same job (video pricing depends on it) without
    # having kept the original submit form's state around.
    duration_seconds: int | None = None
    # Which character/scene skill this job's output actually landed on —
    # the target the client passed, or the id of a skill
    # `execute_asset_output_link` auto-created. `None` for `GENERAL`/`COVER`
    # jobs and for one that never reached settlement. At most one of the two
    # is ever set. The script studio's "返回文案创作" jump-back reads this to
    # auto-relink without the user re-picking from `ScriptLinkPicker`.
    linked_character_id: str | None = None
    linked_scene_id: str | None = None
    # How many of this job's images landed on that card as candidates — the
    # slot already held an approved image (P2-1). The studio uses it to
    # point the owner at the library to approve or discard them.
    candidate_entries: int = 0
    draft_id: str | None = None
    # Echoes `GenerationParams.prompt` back. Lets a client (the image studio's
    # inline version-history strip) show what prompt produced each past
    # iteration without keeping a separate client-side copy of the request.
    prompt: str | None = None
    # `GenerationJob.analysis_result_json` echoed back, typed. `None` for
    # every non-`video_analysis` job, and for a `video_analysis` job that
    # has not settled yet.
    analysis: VideoAnalysisResult | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    cancel_requested: bool = False
    promoted_from_job_id: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
    events: list[JobEventResponse] = Field(default_factory=list)


class UploadPresignRequest(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(ge=1, le=512 * 1024 * 1024)
    checksum_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    purpose: str = Field(
        pattern=(
            r"^(generation_reference|avatar|profile_cover|consent_evidence|learn_media"
            r"|style_gallery_cover|series_logo|episode_preview|video_analysis_source|editor_source"
            r"|editor_export|caption|font|voice_sample)$"
        )
    )
    # The uploader's own declaration that an image/video shows a real person —
    # such a reference then needs a portrait consent (`POST
    # /v1/assets/{asset_id}/consents`) before a generation job may use it.
    depicts_real_person: bool = False


class UploadPresignResponse(ApiModel):
    upload_session_id: str
    upload_url: str
    object_key: str
    expires_at: dt.datetime
    required_headers: dict[str, str] = Field(default_factory=dict)


class UploadCompleteRequest(ApiModel):
    upload_session_id: str


class ExtractFrameRequest(ApiModel):
    """Which single frame to grab from an already-owned video asset — see
    `app.domain.media.service.extract_video_frame`."""

    position: Literal["first", "last"] = "last"


class AssetResponse(ApiModel):
    id: str
    media_type: MediaType
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    url: str | None = None
    moderation_status: str
    is_prototype: bool = False
    ai_generated: bool = False
    depicts_real_person: bool = False


class ProvenanceResponse(ApiModel):
    """AI disclosure for a generated asset.

    `signed` is false until a real C2PA signer is configured; the claim is
    still worth showing, but it must not be presented as verified.
    """

    asset_id: str
    generation_job_id: str | None = None
    claim: dict[str, Any]
    signed: bool = False


class ConsentDeclareRequest(ApiModel):
    """The uploader declares that the real person whose voice or likeness the
    asset carries consented to its use (深度合成管理规定 §14). `evidence_asset_id`
    is an optional `consent_evidence` upload an operator can verify against."""

    consent_type: Literal["voice", "portrait"]
    subject_reference: str = Field(min_length=1, max_length=255)
    evidence_asset_id: str | None = None
    expires_at: dt.datetime | None = None


class ConsentRevokeRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


class ConsentResponse(ApiModel):
    id: str
    asset_id: str
    consent_type: str
    subject_reference: str
    status: str
    has_evidence: bool
    expires_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    created_at: dt.datetime


class CreditBalanceResponse(ApiModel):
    available: int
    reserved: int
    currency: str = "CREDIT"
    # The user's own cap on generation spend per UTC month; null = no cap.
    monthly_spend_limit: int | None = None
    period: str = ""
    period_spent: int = 0
    period_remaining: int | None = None


class SpendLimitRequest(ApiModel):
    """`null` removes the cap."""

    monthly_spend_limit: int | None = Field(default=None, ge=1, le=100_000_000)


class LedgerEntryResponse(ApiModel):
    id: str
    type: LedgerEntryType
    amount: int
    balance_after: int
    job_id: str | None = None
    reason: str | None = None
    created_at: dt.datetime


class CreditPackageResponse(ApiModel):
    id: str
    slug: str
    credits: int
    bonus_credits: int
    price_minor: int
    currency: str
    region: str


class CheckoutRequest(ApiModel):
    package_id: str


class CheckoutResponse(ApiModel):
    payment_intent_id: str
    checkout_url: str
    external_reference: str
    amount_minor: int
    currency: str


class CheckoutConfirmRequest(ApiModel):
    external_reference: str = Field(min_length=1, max_length=128)


class CheckoutConfirmResponse(ApiModel):
    status: str
    available_balance: int


class CheckoutIntentResponse(ApiModel):
    external_reference: str
    package_slug: str
    credits: int
    bonus_credits: int
    amount_minor: int
    currency: str
    status: str


class RedeemCodeRequest(ApiModel):
    code: str = Field(min_length=1, max_length=32)


class RedeemCodeResponse(ApiModel):
    credits_granted: int
    available_balance: int


class NotificationResponse(ApiModel):
    id: str
    type: NotificationType
    title_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    target_type: str | None = None
    target_id: str | None = None
    read: bool = False
    created_at: dt.datetime
    updated_at: dt.datetime


class ReportCreateRequest(ApiModel):
    subject_type: str = Field(pattern=r"^(work|asset|user|comment)$")
    subject_id: str
    reason: ReportReason
    detail: str | None = Field(default=None, max_length=2000)
