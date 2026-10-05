"""`asset_planning`/`asset_output_link` — the two nodes `asset_graph`
(`app.workflows.defaults`) adds on top of the generic image graph: one folds
per-asset-kind guidance into the prompt before generation, the other attaches
a succeeded output to its character/scene target afterwards.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import planner
from app.domain.characters import service as characters_service
from app.domain.errors import NotFound
from app.domain.jobs import state_machine as sm
from app.domain.scenes import service as scenes_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import (
    CharacterViewAngle,
    ImageAssetKind,
    MediaType,
    Operation,
    VideoAssetKind,
)
from app.workflows.configs import (
    AssetOutputAdvanceConfig,
    AssetOutputLinkConfig,
    AssetPlanningConfig,
)
from app.workflows.nodes import (
    _CHARACTER_ANIME_NEGATIVE,
    _CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT,
    _CHARACTER_COMPLETION_FIXED_PROMPTS,
    _CHARACTER_PHOTOREAL_MEDIUM,
    _CHARACTER_PHOTOREAL_NEGATIVE,
    _CHARACTER_SHEET_LAYOUT_SUFFIX,
    execute_asset_output_advance,
    execute_asset_output_link,
    execute_asset_planning,
)
from app.workflows.types import WorkflowContext
from tests.factories import make_job


def _asset(db: Session, owner: User, *, media_type: str = MediaType.IMAGE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"generated/{owner.id}/{media_type}-{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="image/png" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="0" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _ctx(
    db: Session,
    author: User,
    *,
    prompt: str = "一位神秘的女侦探",
    params: dict | None = None,
) -> WorkflowContext:
    job = make_job(db, author, operation=Operation.TEXT_TO_IMAGE)
    return WorkflowContext(
        session=db,
        job=job,
        prompt=prompt,
        params=params or {"prompt": prompt},
    )


# ---- execute_asset_planning ----------------------------------------------


def test_asset_planning_is_a_noop_without_asset_kind(db: Session, author: User) -> None:
    ctx = _ctx(db, author)
    result = execute_asset_planning(ctx, AssetPlanningConfig())
    assert result.port == "ok"
    assert "asset_plan" not in ctx.state
    assert ctx.prompt == "一位神秘的女侦探"


def test_asset_planning_is_a_noop_for_the_general_asset_kind(db: Session, author: User) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.GENERAL.value})
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert "asset_plan" not in ctx.state


def test_asset_planning_folds_enhancements_into_the_prompt(db: Session, author: User) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    result = execute_asset_planning(ctx, AssetPlanningConfig())
    assert result.port == "ok"
    plan = ctx.state["asset_plan"]
    assert plan["subject_name"]
    assert ctx.prompt.startswith("一位神秘的女侦探")
    assert _CHARACTER_SHEET_LAYOUT_SUFFIX in ctx.prompt
    assert ctx.state["_last_agent_run_id"]


def test_asset_planning_folds_negative_prompt_suggestions_for_a_front_pass(
    db: Session, author: User
) -> None:
    """Root cause C: `plan_asset`'s own `negative_prompt_suggestions` used to
    be silently discarded — `ctx.params["negative_prompt"]` stayed `None`
    even though the planner agent run itself produced a real list (see
    `tests.fake_llm_gateway._planner_asset_plan`'s `front` entry)."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    negative_prompt = ctx.params["negative_prompt"]
    assert negative_prompt is not None
    assert "多人入镜" in negative_prompt
    assert "半身裁切" in negative_prompt


def test_asset_planning_preserves_a_caller_supplied_negative_prompt(
    db: Session, author: User
) -> None:
    """A caller-supplied `negative_prompt` must survive alongside the
    planner's own suggestions, the same "extend, never overwrite" contract
    `_plan_enhancements` already applies to a plain `GENERAL` job's plan."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value],
            "negative_prompt": "水印",
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    negative_prompt = ctx.params["negative_prompt"]
    assert "水印" in negative_prompt
    assert "多人入镜" in negative_prompt


def test_asset_planning_stores_the_plan_under_a_custom_output_key(
    db: Session, author: User
) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    execute_asset_planning(ctx, AssetPlanningConfig(output_key="scene_plan"))
    assert "scene_plan" in ctx.state
    assert "asset_plan" not in ctx.state


def test_asset_planning_carries_prior_view_description_for_consistency(
    db: Session, author: User
) -> None:
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value],
            "subject_description": "银色短发、黑色风衣",
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert "银色短发、黑色风衣" in ctx.prompt


@pytest.mark.parametrize("view", [CharacterViewAngle.SIDE.value, CharacterViewAngle.BACK.value])
def test_asset_planning_overrides_the_prompt_for_a_side_or_back_completion_pass(
    db: Session, author: User, view: str
) -> None:
    """A "补全侧面/背面" completion job must never let the caller's own
    prompt — in every one of the three callers that submit this job shape
    (`character-library.tsx`, `image-generation-studio.tsx`, iOS's
    `StudioViewModel.completeViews`), a character's name/description —
    compete with the attached front reference image. The intent handed to
    the planner is always the fixed, view-specific reference-only
    instruction instead, regardless of what free text the caller sent as
    `ctx.prompt` — and it must never mention the *other* view (the old
    shared "侧面/背面" wording literally sat at the start of both passes'
    final prompt in a real job's `job_events`, ambiguous about which single
    angle it wanted)."""
    other_view = (
        CharacterViewAngle.BACK.value
        if view == CharacterViewAngle.SIDE.value
        else CharacterViewAngle.SIDE.value
    )
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={"asset_kind": ImageAssetKind.CHARACTER.value, "character_views": [view]},
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert ctx.prompt.startswith(_CHARACTER_COMPLETION_FIXED_PROMPTS[view])
    assert "一位神秘的女侦探" not in ctx.prompt
    assert _CHARACTER_COMPLETION_FIXED_PROMPTS[other_view] not in ctx.prompt


@pytest.mark.parametrize("view", [CharacterViewAngle.SIDE.value, CharacterViewAngle.BACK.value])
def test_asset_planning_seeds_the_anti_collage_negative_for_a_completion_pass(
    db: Session, author: User, view: str
) -> None:
    """Defense-in-depth for root cause A/B: even if the reference image
    still doesn't land for some reason, a hardcoded negative rules out the
    multi-panel turnaround-sheet layout the model actually produced in a
    real job."""
    ctx = _ctx(
        db,
        author,
        params={"asset_kind": ImageAssetKind.CHARACTER.value, "character_views": [view]},
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert _CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT in ctx.params["negative_prompt"]


def test_asset_planning_resets_prompt_and_negative_prompt_between_loop_passes(
    db: Session, author: User
) -> None:
    """The second pass of a multi-view completion job must not inherit the
    first pass's view-specific prompt or negative prompt — the same class
    of cross-view leakage as root cause B, but for `execute_asset_planning`
    being re-entered directly (`execute_asset_output_advance`'s loop-back
    edge) rather than through the generic planner."""
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [
                CharacterViewAngle.SIDE.value,
                CharacterViewAngle.BACK.value,
            ],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert ctx.prompt.startswith(_CHARACTER_COMPLETION_FIXED_PROMPTS[CharacterViewAngle.SIDE.value])
    side_negative = ctx.params["negative_prompt"]
    assert "五官被头发遮挡" in side_negative

    ctx.state["_current_character_view"] = CharacterViewAngle.BACK.value
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert ctx.prompt.startswith(_CHARACTER_COMPLETION_FIXED_PROMPTS[CharacterViewAngle.BACK.value])
    assert _CHARACTER_COMPLETION_FIXED_PROMPTS[CharacterViewAngle.SIDE.value] not in ctx.prompt
    back_negative = ctx.params["negative_prompt"]
    assert "五官被头发遮挡" not in back_negative
    assert "露出正面五官" in back_negative


def test_asset_planning_gives_each_later_view_a_fresh_route_budget(
    db: Session, author: User
) -> None:
    """The second view must not inherit the first view's spent
    `route_attempts`, its excluded providers or its stale `failure_code` —
    but `attempt_seq` (which names output object keys) keeps counting."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value, CharacterViewAngle.SIDE.value],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    # The front view needed a retry before it succeeded.
    ctx.state.update(
        route_attempts=2,
        attempt_seq=2,
        tried_providers={"provider_a"},
        failure_code="PROVIDER_TEMPORARY_FAILURE",
        asset_id=_asset(db, author).id,
    )
    execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())

    execute_asset_planning(ctx, AssetPlanningConfig())

    assert ctx.state["route_attempts"] == 0
    assert ctx.state["tried_providers"] == set()
    assert "failure_code" not in ctx.state
    assert ctx.state["attempt_seq"] == 2


def test_asset_planning_leaves_the_first_pass_routing_state_alone(
    db: Session, author: User
) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["tried_providers"] = {"provider_a"}
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert ctx.state["tried_providers"] == {"provider_a"}


def test_asset_planning_appends_the_sheet_suffix_on_a_front_pass(db: Session, author: User) -> None:
    """The `front` pass — including a plain single-view job with no
    `character_views` at all — keeps the caller's identity prompt and
    appends the sheet-layout suffix. Only a side/back completion pass
    replaces the prompt entirely."""
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert ctx.prompt.startswith("一位神秘的女侦探")
    assert _CHARACTER_SHEET_LAYOUT_SUFFIX in ctx.prompt
    assert _CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT not in (
        ctx.params.get("negative_prompt") or ""
    )


def test_asset_plan_prompt_locks_character_visual_medium() -> None:
    prompt = planner.ASSET_PLAN_SYSTEM_PROMPT
    assert "真人写实影视短剧造型" in prompt
    assert "禁止改成另一种" in prompt
    assert "动漫/二次元/卡通" in prompt


def test_asset_plan_prompt_locks_scene_single_camera() -> None:
    prompt = planner.ASSET_PLAN_SYSTEM_PROMPT
    assert "单一机位" in prompt
    assert "单一连续空间" in prompt
    assert "分割构图" in prompt
    assert "关闭的遮挡保持关闭" in prompt
    assert "门大开的全屋透视" in prompt
    assert "禁止分割构图" in prompt


def test_asset_planning_locks_a_front_pass_without_a_medium_to_photoreal(
    db: Session, author: User
) -> None:
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={"asset_kind": ImageAssetKind.CHARACTER.value},
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert _CHARACTER_PHOTOREAL_MEDIUM in ctx.prompt
    assert _CHARACTER_PHOTOREAL_NEGATIVE in (ctx.params.get("negative_prompt") or "")


def test_asset_planning_keeps_an_explicit_anime_medium_on_a_front_pass(
    db: Session, author: User
) -> None:
    ctx = _ctx(
        db,
        author,
        prompt="二维日系动漫造型，银发高中生",
        params={"asset_kind": ImageAssetKind.CHARACTER.value},
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert _CHARACTER_PHOTOREAL_MEDIUM not in ctx.prompt
    assert "二维日系动漫造型" in ctx.prompt
    assert _CHARACTER_ANIME_NEGATIVE in (ctx.params.get("negative_prompt") or "")
    assert _CHARACTER_PHOTOREAL_NEGATIVE not in (ctx.params.get("negative_prompt") or "")


def test_asset_planning_does_not_lock_medium_on_a_completion_pass(
    db: Session, author: User
) -> None:
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert _CHARACTER_PHOTOREAL_MEDIUM not in ctx.prompt
    assert _CHARACTER_PHOTOREAL_NEGATIVE not in (ctx.params.get("negative_prompt") or "")


def test_asset_planning_does_not_append_the_sheet_suffix_on_a_completion_pass(
    db: Session, author: User
) -> None:
    ctx = _ctx(
        db,
        author,
        prompt="一位神秘的女侦探",
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert _CHARACTER_SHEET_LAYOUT_SUFFIX not in ctx.prompt
    assert ctx.prompt.startswith(_CHARACTER_COMPLETION_FIXED_PROMPTS[CharacterViewAngle.SIDE.value])


# ---- execute_asset_output_link --------------------------------------------


def test_asset_output_link_is_a_noop_in_dry_run(db: Session, author: User) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    ctx.dry_run = True
    ctx.state["asset_id"] = "ast_whatever"
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert result.port == "ok"


def test_asset_output_link_is_a_noop_without_an_asset_id(db: Session, author: User) -> None:
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert result.port == "ok"


def test_asset_output_link_is_a_noop_for_the_general_asset_kind(db: Session, author: User) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.GENERAL.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert "created_character_id" not in ctx.state


def test_asset_output_link_attaches_to_an_existing_target_character(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
        },
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    refreshed = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert refreshed.reference_asset_ids == [asset.id]
    assert refreshed.reference_assets[0]["view"] == CharacterViewAngle.FRONT.value
    assert "created_character_id" not in ctx.state


def test_asset_output_link_keeps_the_approved_sheet_and_files_a_candidate(
    db: Session, author: User
) -> None:
    """A regenerated front sheet must not silently replace the one the
    owner already settled on (P2-1): it waits beside it as a candidate."""
    from app.domain.asset_variants import service as asset_variants_service

    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    produced = []
    for _ in range(2):
        asset = _asset(db, author)
        ctx = _ctx(
            db,
            author,
            params={
                "asset_kind": ImageAssetKind.CHARACTER.value,
                "target_character_id": character.id,
            },
        )
        ctx.state["asset_id"] = asset.id
        execute_asset_output_link(ctx, AssetOutputLinkConfig())
        produced.append(asset.id)

    refreshed = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert refreshed.reference_asset_ids == [produced[0]]
    statuses = {e.asset_id: e.status for e in asset_variants_service.entries(refreshed.skill)}
    assert statuses == {produced[0]: "approved", produced[1]: "candidate"}


def test_asset_output_link_auto_creates_a_character_when_no_target_is_given(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    ctx.state["asset_id"] = asset.id
    ctx.state["asset_plan"] = {"subject_name": "神秘女侦探"}
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_character_id"]
    character = characters_service.get_character(db, user_id=author.id, character_id=created_id)
    assert character.name == "神秘女侦探"
    assert character.reference_asset_ids == [asset.id]


def test_asset_output_link_reuses_an_existing_character_with_the_same_name(
    db: Session, author: User
) -> None:
    """A script-studio batch (or a second job with the same subject_name_hint)
    must attach to the owner's existing same-name card — titles are unique
    per owner, so auto-creating a twin would 422 and drop the output."""
    existing = characters_service.create_character(
        db,
        user_id=author.id,
        name="林彻",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={"asset_kind": ImageAssetKind.CHARACTER.value, "subject_name_hint": "林彻"},
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    assert "created_character_id" not in ctx.state
    assert ctx.job.linked_character_id == existing.id
    refreshed = characters_service.get_character(db, user_id=author.id, character_id=existing.id)
    assert refreshed.reference_asset_ids == [asset.id]
    assert len(characters_service.list_characters(db, user_id=author.id)) == 1


def test_asset_output_link_records_linked_character_id_across_a_refresh(
    db: Session, author: User
) -> None:
    """`ctx.job.linked_character_id` must survive `db.refresh(ctx.job)` — the
    exact thing `WorkflowEngine._execute_node`'s `_cancel_if_requested` does
    right after every node runs (`app.workflows.runner`). The session is
    `autoflush=False` (`app.db`), so a mutation the node forgets to flush is
    silently discarded by that refresh, reverting the field back to `None`
    even though the character/reference-asset attach itself (a separate,
    already-flushed write) went through fine.
    """
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    ctx.state["asset_id"] = asset.id
    ctx.state["asset_plan"] = {"subject_name": "神秘女侦探"}
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    db.refresh(ctx.job)
    assert ctx.job.linked_character_id == ctx.state["created_character_id"]


def test_asset_output_link_does_not_auto_create_when_disabled(db: Session, author: User) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig(auto_create_character=False))

    assert "created_character_id" not in ctx.state
    assert characters_service.list_characters(db, user_id=author.id) == []


def test_asset_output_link_is_a_noop_when_auto_attach_is_disabled(
    db: Session, author: User
) -> None:
    """`auto_attach_asset=False` lets the client borrow a character's front
    view for side/back consistency without writing the new output back."""
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value],
            "target_character_id": character.id,
            "auto_attach_asset": False,
        },
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    refreshed = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert refreshed.reference_asset_ids == []


def test_asset_output_link_attaches_to_an_existing_target_scene(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={"asset_kind": ImageAssetKind.SCENE.value, "target_scene_id": scene.id},
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    refreshed = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert refreshed.reference_asset_ids == [asset.id]


def test_asset_output_link_auto_creates_a_scene_when_no_target_is_given(
    db: Session, author: User
) -> None:
    """Scenes now reach parity with characters: no `target_scene_id` auto-
    creates a brand-new scene skill instead of leaving the output
    unattached."""
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["asset_id"] = asset.id
    ctx.state["asset_plan"] = {"subject_name": "深夜便利店"}
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_scene_id"]
    scene = scenes_service.get_scene(db, user_id=author.id, scene_id=created_id)
    assert scene.name == "深夜便利店"
    assert scene.reference_asset_ids == [asset.id]


def test_asset_output_link_auto_created_scene_falls_back_to_a_kind_specific_default_name(
    db: Session, author: User
) -> None:
    """Without a plan or a hint, a scene auto-create must not inherit the
    character path's "新角色" fallback."""
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_scene_id"]
    scene = scenes_service.get_scene(db, user_id=author.id, scene_id=created_id)
    assert scene.name == "新场景"


def test_asset_output_link_does_not_auto_create_scene_when_disabled(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig(auto_create_scene=False))

    assert "created_scene_id" not in ctx.state
    assert scenes_service.list_scenes(db, user_id=author.id) == []


def test_asset_output_link_uses_subject_name_hint_over_the_planner_guess(
    db: Session, author: User
) -> None:
    """The script studio's jump-out already knows the exact character name;
    it must win over whatever the planner guessed from the prompt."""
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={"asset_kind": ImageAssetKind.CHARACTER.value, "subject_name_hint": "林夏"},
    )
    ctx.state["asset_id"] = asset.id
    ctx.state["asset_plan"] = {"subject_name": "神秘女侦探"}
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_character_id"]
    character = characters_service.get_character(db, user_id=author.id, character_id=created_id)
    assert character.name == "林夏"


def test_asset_output_link_cover_kind_has_no_library_to_attach_to(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.COVER.value})
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert result.port == "ok"
    assert characters_service.list_characters(db, user_id=author.id) == []


def test_asset_output_link_character_action_auto_creates_a_character_when_no_target_is_given(
    db: Session, author: User
) -> None:
    """The video-side counterpart of
    `test_asset_output_link_auto_creates_a_character_when_no_target_is_given`."""
    asset = _asset(db, author, media_type=MediaType.VIDEO)
    ctx = _ctx(db, author, params={"video_asset_kind": VideoAssetKind.CHARACTER_ACTION.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_character_id"]
    character = characters_service.get_character(db, user_id=author.id, character_id=created_id)
    assert character.name == "新角色"
    assert [clip["asset_id"] for clip in character.action_clips] == [asset.id]
    assert ctx.job.linked_character_id == created_id


def test_asset_output_link_character_action_reuses_an_existing_character_with_the_same_name(
    db: Session, author: User
) -> None:
    """Regression test for the production defect this fix closes: a second
    `character_action` job landing on the same default name ("新角色") must
    reuse the owner's existing card, exactly like the image path's
    `test_asset_output_link_reuses_an_existing_character_with_the_same_name`
    — not silently drop the clip because `create_character` raised
    `ValidationFailed`. Before this fix, `_link_character_action_output` had
    no same-name reuse step and this reproduced the exact failure seen in
    production logs (`asset_output_link failed … ValidationFailed: 角色名称
    已存在。`, `linked_character_id` left `None`).
    """
    existing = characters_service.create_character(
        db,
        user_id=author.id,
        name="新角色",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author, media_type=MediaType.VIDEO)
    ctx = _ctx(db, author, params={"video_asset_kind": VideoAssetKind.CHARACTER_ACTION.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    assert "created_character_id" not in ctx.state
    assert ctx.job.linked_character_id == existing.id
    refreshed = characters_service.get_character(db, user_id=author.id, character_id=existing.id)
    assert [clip["asset_id"] for clip in refreshed.action_clips] == [asset.id]
    assert len(characters_service.list_characters(db, user_id=author.id)) == 1


def test_asset_output_link_character_action_attaches_to_an_existing_target_character(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="周岩",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    asset = _asset(db, author, media_type=MediaType.VIDEO)
    ctx = _ctx(
        db,
        author,
        params={
            "video_asset_kind": VideoAssetKind.CHARACTER_ACTION.value,
            "target_character_id": character.id,
        },
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    refreshed = characters_service.get_character(db, user_id=author.id, character_id=character.id)
    assert [clip["asset_id"] for clip in refreshed.action_clips] == [asset.id]
    assert "created_character_id" not in ctx.state


def test_asset_output_link_falls_back_to_a_new_character_when_the_target_is_gone(
    db: Session, author: User
) -> None:
    """`target_character_id` may be stale — e.g. the script studio cached it
    before the user deleted that character from the library. Rather than
    losing the generated output, the node must auto-create a replacement
    the same way it would have with no target at all, and thread the new
    id back onto `ctx.job.linked_character_id` so the "返回文案创作" jump-back
    can re-link the script to it."""
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": "ch_does_not_exist",
            "subject_name_hint": "叶文洁",
        },
    )
    ctx.state["asset_id"] = asset.id
    with pytest.raises(NotFound):
        characters_service.get_character(db, user_id=author.id, character_id="ch_does_not_exist")

    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())

    assert result.port == "ok"
    created_id = ctx.state["created_character_id"]
    assert created_id != "ch_does_not_exist"
    character = characters_service.get_character(db, user_id=author.id, character_id=created_id)
    assert character.name == "叶文洁"
    assert character.reference_asset_ids == [asset.id]
    assert ctx.job.linked_character_id == created_id


def test_asset_output_link_falls_back_to_a_new_scene_when_the_target_is_gone(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.SCENE.value,
            "target_scene_id": "sc_does_not_exist",
            "subject_name_hint": "深夜便利店",
        },
    )
    ctx.state["asset_id"] = asset.id
    with pytest.raises(NotFound):
        scenes_service.get_scene(db, user_id=author.id, scene_id="sc_does_not_exist")

    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())

    assert result.port == "ok"
    created_id = ctx.state["created_scene_id"]
    assert created_id != "sc_does_not_exist"
    scene = scenes_service.get_scene(db, user_id=author.id, scene_id=created_id)
    assert scene.name == "深夜便利店"
    assert scene.reference_asset_ids == [asset.id]
    assert ctx.job.linked_scene_id == created_id


def test_asset_output_link_stays_a_noop_when_target_is_gone_and_auto_create_is_disabled(
    db: Session, author: User
) -> None:
    """A caller that explicitly opted out of auto-create (`auto_attach_asset`'s
    sibling flag) must still see a plain no-op, not a fallback character —
    same "never fail the job" contract as before, just also covering a
    stale target rather than only a missing one."""
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": "ch_does_not_exist",
        },
    )
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig(auto_create_character=False))

    assert result.port == "ok"
    assert "created_character_id" not in ctx.state
    assert characters_service.list_characters(db, user_id=author.id) == []


def test_asset_output_link_stays_a_noop_when_scene_target_is_gone_and_auto_create_is_disabled(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.SCENE.value,
            "target_scene_id": "sc_does_not_exist",
        },
    )
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig(auto_create_scene=False))

    assert result.port == "ok"
    assert "created_scene_id" not in ctx.state
    assert scenes_service.list_scenes(db, user_id=author.id) == []


# ---- execute_asset_output_advance -----------------------------------------


def test_asset_output_advance_takes_the_done_port_for_a_single_view_job(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert result.port == "done"
    assert ctx.state["asset_outputs"] == [{"asset_id": asset.id, "view": "front"}]


def test_asset_output_advance_takes_the_done_port_for_a_non_character_kind(
    db: Session, author: User
) -> None:
    """`scene`/`cover`/`general` never loop, no matter how many views were
    (meaninglessly) requested."""
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert result.port == "done"
    assert ctx.state["asset_outputs"] == [{"asset_id": asset.id, "view": "scene"}]


def test_asset_output_advance_loops_through_every_requested_character_view(
    db: Session, author: User
) -> None:
    """A "补全侧面/背面" completion job walks `side` then `back`, recording an
    output for each pass and looping back via the `next` port in between."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value, CharacterViewAngle.BACK.value],
        },
    )

    side_asset = _asset(db, author)
    ctx.state["asset_id"] = side_asset.id
    first = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert first.port == "next"
    assert ctx.state["_current_character_view"] == CharacterViewAngle.BACK.value
    assert ctx.state["asset_outputs"] == [
        {
            "asset_id": side_asset.id,
            "view": "side",
            "camera": {"azimuth": 90, "elevation": 0, "distance": "medium"},
        }
    ]

    back_asset = _asset(db, author)
    ctx.state["asset_id"] = back_asset.id
    second = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert second.port == "done"
    assert ctx.state["asset_outputs"] == [
        {
            "asset_id": side_asset.id,
            "view": "side",
            "camera": {"azimuth": 90, "elevation": 0, "distance": "medium"},
        },
        {
            "asset_id": back_asset.id,
            "view": "back",
            "camera": {"azimuth": 180, "elevation": 0, "distance": "medium"},
        },
    ]


def test_asset_output_advance_still_loops_in_a_dry_run_with_no_asset_id(
    db: Session, author: User
) -> None:
    """A sandbox try-it never actually produces an asset, but the loop must
    still walk the whole graph so an operator can see every node fire."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value, CharacterViewAngle.SIDE.value],
        },
    )
    ctx.dry_run = True

    first = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert first.port == "next"
    assert ctx.state["asset_outputs"] == []

    second = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert second.port == "done"
    assert ctx.state["asset_outputs"] == []


def test_asset_output_link_attaches_every_looped_view_to_the_same_character(
    db: Session, author: User
) -> None:
    """The full `asset_output_advance` -> `asset_output_link` pipeline for a
    completion job: both views land on the one auto-created character, not
    two separate ones."""
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.SIDE.value, CharacterViewAngle.BACK.value],
        },
    )
    ctx.state["asset_plan"] = {"subject_name": "神秘女侦探"}

    side_asset = _asset(db, author)
    ctx.state["asset_id"] = side_asset.id
    assert execute_asset_output_advance(ctx, AssetOutputAdvanceConfig()).port == "next"

    back_asset = _asset(db, author)
    ctx.state["asset_id"] = back_asset.id
    assert execute_asset_output_advance(ctx, AssetOutputAdvanceConfig()).port == "done"

    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    created_id = ctx.state["created_character_id"]
    character = characters_service.get_character(db, user_id=author.id, character_id=created_id)
    assert character.reference_asset_ids == [side_asset.id, back_asset.id]
    views = {a["asset_id"]: a["view"] for a in character.reference_assets}
    assert views[side_asset.id] == CharacterViewAngle.SIDE.value
    assert views[back_asset.id] == CharacterViewAngle.BACK.value


# ---- progress rescaling across the loop -----------------------------------


def test_progress_never_regresses_across_a_multi_view_character_loop(
    db: Session, author: User
) -> None:
    """`asset_planning`'s fixed progress constant (16) fires once per
    produced view — without rescaling, the client-visible number would jump
    78% -> 16% -> 78% on every loop-back through `asset_planning` (see
    `execute_asset_output_advance`). Every job event's `progress` column must
    stay non-decreasing for the whole job, mirroring the same invariant
    `test_generation_lifecycle.py` already asserts for async video polling.
    """
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [
                CharacterViewAngle.FRONT.value,
                CharacterViewAngle.SIDE.value,
                CharacterViewAngle.BACK.value,
            ],
        },
    )

    for _ in range(3):
        execute_asset_planning(ctx, AssetPlanningConfig())
        asset = _asset(db, author)
        ctx.state["asset_id"] = asset.id
        execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())

    progress_values = [event.progress for event in sm.events_since(db, ctx.job.id, 0)]
    assert len(progress_values) == 3
    assert progress_values == sorted(progress_values)
    # Each view's `asset_planning` pass must land strictly ahead of the last,
    # not just tie — otherwise the client can't tell view 2 apart from view 1.
    assert len(set(progress_values)) == 3


def test_progress_is_unchanged_for_a_single_view_character_job(db: Session, author: User) -> None:
    """The rescale is a no-op outside the multi-view loop — a plain
    single-view job still reports `asset_planning`'s raw constant."""
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.CHARACTER.value})
    execute_asset_planning(ctx, AssetPlanningConfig())

    events = sm.events_since(db, ctx.job.id, 0)
    assert len(events) == 1
    assert events[0].progress == 16


# ---- labelled write-back (outfits, expressions, scene variants) ----------


def test_asset_output_link_files_an_outfit_sheet_under_its_label(db: Session, author: User) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    daily = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=daily.id, view="front"
    )
    wedding = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
            "character_outfit_label": "婚礼",
        },
    )
    ctx.state["asset_id"] = wedding.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    entries = characters_service.get_character(
        db, user_id=author.id, character_id=character.id
    ).reference_assets
    by_id = {entry["asset_id"]: entry for entry in entries}
    assert by_id[daily.id]["label"] is None
    assert by_id[wedding.id]["view"] == "front"
    assert by_id[wedding.id]["label"] == "婚礼"


def test_asset_output_link_files_an_expression_sheet_as_a_labelled_extra(
    db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    front = _asset(db, author)
    characters_service.append_reference_asset(
        db, user_id=author.id, character_id=character.id, asset_id=front.id, view="front"
    )
    sheet = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
            "character_expressions": ["smirk", "restrained"],
        },
    )
    ctx.state["asset_id"] = sheet.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    by_id = {
        entry["asset_id"]: entry
        for entry in characters_service.get_character(
            db, user_id=author.id, character_id=character.id
        ).reference_assets
    }
    assert front.id in by_id
    assert by_id[sheet.id]["view"] == CharacterViewAngle.GENERAL.value
    assert by_id[sheet.id]["label"] == "表情·冷笑/隐忍"


def test_asset_output_link_labels_a_scene_variant_with_its_presets(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    )
    asset = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.SCENE.value,
            "target_scene_id": scene.id,
            "scene_lighting": "night_interior",
            "scene_state": "damage_medium",
        },
    )
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    entries = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id).reference_assets
    assert entries[-1]["label"] == "夜·室内 / 战损·中"


def test_asset_output_link_keeps_attaching_after_one_output_fails(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    good = _asset(db, author)
    ctx = _ctx(
        db,
        author,
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "target_character_id": character.id,
        },
    )
    ctx.state["asset_outputs"] = [
        {"asset_id": "ast_missing", "view": "front"},
        {"asset_id": good.id, "view": "side"},
    ]
    execute_asset_output_link(ctx, AssetOutputLinkConfig())

    ids = characters_service.get_character(
        db, user_id=author.id, character_id=character.id
    ).reference_asset_ids
    assert ids == [good.id]


# ---- builder-driven passes ---------------------------------------------------


def test_asset_planning_builds_an_expression_grid_and_drops_sheet_suggestions(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = planner.plan_asset

    def sheet_happy_planner(*args, **kwargs):
        outcome = real(*args, **kwargs)
        assert kwargs["asset_pass"] == "character_expressions"
        outcome.data["prompt_enhancements"] = ["左侧全身三视图", "五官一致"]
        return outcome

    monkeypatch.setattr(planner, "plan_asset", sheet_happy_planner)
    ctx = _ctx(
        db,
        author,
        prompt="林夏",
        params={
            "asset_kind": ImageAssetKind.CHARACTER.value,
            "character_views": [CharacterViewAngle.FRONT.value],
            "character_expressions": ["smile", "anger"],
            "reference_asset_ids": ["ast_sheet"],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())

    assert _CHARACTER_SHEET_LAYOUT_SUFFIX not in ctx.prompt
    assert "三视图" not in ctx.prompt
    assert "五官一致" in ctx.prompt
    assert "表情合集图" in ctx.prompt


def test_asset_planning_prefixes_a_scene_variant_only_with_a_reference(
    db: Session, author: User
) -> None:
    with_ref = _ctx(
        db,
        author,
        prompt="老式客厅",
        params={
            "asset_kind": ImageAssetKind.SCENE.value,
            "scene_lighting": "dusk",
            "reference_asset_ids": ["ast_master"],
        },
    )
    execute_asset_planning(with_ref, AssetPlanningConfig())
    assert with_ref.prompt.startswith("以参考图1为基准")
    assert "黄昏" in with_ref.prompt

    without_ref = _ctx(
        db,
        author,
        prompt="老式客厅",
        params={"asset_kind": ImageAssetKind.SCENE.value, "scene_lighting": "dusk"},
    )
    execute_asset_planning(without_ref, AssetPlanningConfig())
    assert not without_ref.prompt.startswith("以参考图1为基准")
    assert "黄昏" in without_ref.prompt


def test_a_scene_variant_set_runs_one_pass_per_variant(db: Session, author: User) -> None:
    ctx = _ctx(
        db,
        author,
        prompt="老式客厅",
        params={
            "asset_kind": ImageAssetKind.SCENE.value,
            "scene_variants": [{"lighting": "day"}, {"state": "damage_heavy"}],
        },
    )
    execute_asset_planning(ctx, AssetPlanningConfig())
    assert "白天" in ctx.prompt and "重度战损" not in ctx.prompt
    ctx.state["asset_id"] = _asset(db, author).id
    assert execute_asset_output_advance(ctx, AssetOutputAdvanceConfig()).port == "next"

    execute_asset_planning(ctx, AssetPlanningConfig())
    assert "重度战损" in ctx.prompt and "白天：" not in ctx.prompt
    ctx.state["asset_id"] = _asset(db, author).id
    assert execute_asset_output_advance(ctx, AssetOutputAdvanceConfig()).port == "done"

    assert [entry["label"] for entry in ctx.state["asset_outputs"]] == ["白天", "战损·重"]
