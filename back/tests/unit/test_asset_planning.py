"""`asset_planning`/`asset_output_link` — the two nodes `image_asset_graph`
(`app.workflows.defaults`) adds on top of the generic image graph: one folds
per-asset-kind guidance into the prompt before generation, the other attaches
a succeeded output to its character/scene target afterwards.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.errors import NotFound
from app.domain.jobs import state_machine as sm
from app.domain.scenes import service as scenes_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import CharacterViewAngle, ImageAssetKind, MediaType, Operation
from app.workflows.configs import (
    AssetOutputAdvanceConfig,
    AssetOutputLinkConfig,
    AssetPlanningConfig,
)
from app.workflows.nodes import (
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
    assert ctx.prompt.startswith("一位神秘的女侦探，")
    assert ctx.state["_last_agent_run_id"]


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


def test_asset_output_link_scene_kind_without_a_target_is_a_noop(db: Session, author: User) -> None:
    """Unlike characters, scenes have no auto-create path — no target means
    the output stays a plain generated asset."""
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.SCENE.value})
    ctx.state["asset_id"] = asset.id
    execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert scenes_service.list_scenes(db, user_id=author.id) == []


def test_asset_output_link_cover_kind_has_no_library_to_attach_to(
    db: Session, author: User
) -> None:
    asset = _asset(db, author)
    ctx = _ctx(db, author, params={"asset_kind": ImageAssetKind.COVER.value})
    ctx.state["asset_id"] = asset.id
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert result.port == "ok"
    assert characters_service.list_characters(db, user_id=author.id) == []


def test_asset_output_link_swallows_a_missing_target_character_instead_of_failing(
    db: Session, author: User
) -> None:
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
    with pytest.raises(NotFound):
        characters_service.get_character(db, user_id=author.id, character_id="ch_does_not_exist")
    result = execute_asset_output_link(ctx, AssetOutputLinkConfig())
    assert result.port == "ok"


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
    assert ctx.state["asset_outputs"] == [{"asset_id": side_asset.id, "view": "side"}]

    back_asset = _asset(db, author)
    ctx.state["asset_id"] = back_asset.id
    second = execute_asset_output_advance(ctx, AssetOutputAdvanceConfig())
    assert second.port == "done"
    assert ctx.state["asset_outputs"] == [
        {"asset_id": side_asset.id, "view": "side"},
        {"asset_id": back_asset.id, "view": "back"},
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
