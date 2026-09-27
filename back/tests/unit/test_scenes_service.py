"""Scene library service — the adapter layer over `CreationSkill`
(`category=scene_asset`), see `app.domain.scenes.service.SceneView`.

`test_reference_asset_writes_survive_a_fresh_reload_from_the_database` and
its character-side sibling in `test_characters_service.py` guard a real bug
this module used to have: `_payload`/`_reference_assets` used to hand back the
*same* dict/entry objects stored inside `CreationSkill.params_json`, and
every mutator (`append_reference_asset`, `update_reference_asset`,
`update_scene`) mutated them in place before reassigning the column. That
mutates the JSON column's "before" value together with the "after" value it
is compared against at flush time, so SQLAlchemy sees no change and silently
skips the `UPDATE`. `session.expire_all()` forces a fresh reload from the
database without depending on GC timing, so a regression here fails
deterministically.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, User
from app.models.base import new_id
from app.models.enums import MediaType, ModerationStatus
from tests.conftest import make_user


def _asset(db: Session, owner: User, *, media_type: str = MediaType.IMAGE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{owner.id}/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="image/png" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def test_apply_scene_refs_is_a_noop_without_scene_ids(db: Session, author: User) -> None:
    params: dict[str, object] = {"reference_asset_ids": ["ast_existing"]}
    scenes_service.apply_scene_refs(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == ["ast_existing"]


def test_apply_scene_refs_merges_reference_assets(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    first = _asset(db, author)
    second = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=first.id
    )
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=second.id
    )

    params: dict[str, object] = {"scene_ids": [scene.id], "reference_asset_ids": ["ast_existing"]}
    scenes_service.apply_scene_refs(db, user_id=author.id, params=params)
    assert params["reference_asset_ids"] == ["ast_existing", first.id, second.id]


def test_apply_scene_refs_respects_the_job_reference_budget(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    for _ in range(3):
        scenes_service.append_reference_asset(
            db, user_id=author.id, scene_id=scene.id, asset_id=_asset(db, author).id
        )

    params: dict[str, object] = {
        "scene_ids": [scene.id],
        "reference_asset_ids": [f"ast_existing_{i}" for i in range(8)],
    }
    scenes_service.apply_scene_refs(db, user_id=author.id, params=params)
    # 8 existing + only 1 of the scene's (up to 4, capped at 4 by MAX_REFERENCE_ASSETS
    # replacement rule for repeated `general` views) refs fits under the 9-slot cap.
    assert len(params["reference_asset_ids"]) == 9


def test_apply_scene_refs_rejects_someone_elses_scene(db: Session, author: User) -> None:
    other = make_user(db, email="other@example.com", handle="other", display_name="别人")
    scene = scenes_service.create_scene(
        db, user_id=other.id, name="别人的场景", description=None, reference_asset_ids=[]
    )
    db.flush()

    params: dict[str, object] = {"scene_ids": [scene.id]}
    with pytest.raises(NotFound):
        scenes_service.apply_scene_refs(db, user_id=author.id, params=params)


def test_apply_scene_refs_rejects_too_many_scenes(db: Session, author: User) -> None:
    scene_ids = [
        scenes_service.create_scene(
            db, user_id=author.id, name=f"场景{i}", description=None, reference_asset_ids=[]
        ).id
        for i in range(5)
    ]
    db.flush()
    params: dict[str, object] = {"scene_ids": scene_ids}
    with pytest.raises(ValidationFailed):
        scenes_service.apply_scene_refs(db, user_id=author.id, params=params)


# ---- CRUD --------------------------------------------------------------


def test_create_get_update_delete_round_trip(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description="深夜的便利店", reference_asset_ids=[]
    )
    fetched = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert fetched.name == "便利店"
    assert fetched.description == "深夜的便利店"

    updated = scenes_service.update_scene(
        db, user_id=author.id, scene_id=scene.id, name="深夜便利店", description="新描述"
    )
    assert updated.name == "深夜便利店"
    assert updated.description == "新描述"

    scenes_service.delete_scene(db, user_id=author.id, scene_id=scene.id)
    with pytest.raises(NotFound):
        scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)


def test_a_scene_is_scoped_to_its_owner(db: Session, author: User) -> None:
    other = make_user(db, email="other4@example.com", handle="other4", display_name="别人")
    scene = scenes_service.create_scene(
        db, user_id=other.id, name="别人的场景", description=None, reference_asset_ids=[]
    )
    with pytest.raises(NotFound):
        scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)


def test_create_rejects_more_than_four_reference_assets(db: Session, author: User) -> None:
    assets = [_asset(db, author) for _ in range(5)]
    with pytest.raises(ValidationFailed):
        scenes_service.create_scene(
            db,
            user_id=author.id,
            name="太多素材",
            description=None,
            reference_asset_ids=[a.id for a in assets],
        )


def test_create_rejects_someone_elses_asset(db: Session, author: User) -> None:
    other = make_user(db, email="other2@example.com", handle="other2", display_name="别人")
    asset = _asset(db, other)
    with pytest.raises(NotFound):
        scenes_service.create_scene(
            db,
            user_id=author.id,
            name="用了别人的素材",
            description=None,
            reference_asset_ids=[asset.id],
        )


# ---- Reference asset persistence (regression coverage) --------------------


def test_reference_asset_writes_survive_a_fresh_reload_from_the_database(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    asset = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=asset.id, view="establishing"
    )

    db.expire_all()
    reloaded = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert reloaded.reference_asset_ids == [asset.id]
    assert reloaded.reference_assets[0]["view"] == "establishing"


def test_update_reference_asset_view_survives_a_fresh_reload(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    asset = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=asset.id
    )

    scenes_service.update_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=asset.id, view="detail", label="特写"
    )

    db.expire_all()
    reloaded = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert reloaded.reference_assets[0]["view"] == "detail"
    assert reloaded.reference_assets[0]["label"] == "特写"


def test_update_reference_asset_rejects_an_unknown_asset_id(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    with pytest.raises(NotFound):
        scenes_service.update_reference_asset(
            db, user_id=author.id, scene_id=scene.id, asset_id="ast_missing", view="general"
        )


def test_remove_reference_asset_survives_a_fresh_reload(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    asset = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=asset.id
    )
    scenes_service.remove_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=asset.id
    )

    db.expire_all()
    reloaded = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert reloaded.reference_assets == []


def test_append_reference_asset_replaces_the_same_views_prior_image(
    db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    first = _asset(db, author)
    second = _asset(db, author)
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=first.id, view="establishing"
    )
    scenes_service.append_reference_asset(
        db, user_id=author.id, scene_id=scene.id, asset_id=second.id, view="establishing"
    )

    db.expire_all()
    reloaded = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert reloaded.reference_asset_ids == [first.id, second.id]


def test_editing_a_published_scene_withdraws_it_to_draft(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    scenes_service.publish_scene(db, user_id=author.id, scene_id=scene.id)
    published = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert published.status == "pending_review"

    scenes_service.update_scene(db, user_id=author.id, scene_id=scene.id, name="改名")
    reloaded = scenes_service.get_scene(db, user_id=author.id, scene_id=scene.id)
    assert reloaded.status == "draft"
    assert reloaded.visibility == "private"
    # The review request goes with it — no open queue item left for a
    # reviewer to approve into a 409.
    queue_item = skill_library_service._queue_item_for(db, db.get(CreationSkill, scene.id))
    assert queue_item is not None
    assert queue_item.status == ModerationStatus.REJECTED
    assert queue_item.reason_code == "withdrawn_by_owner"


# ---- Publish / withdraw -----------------------------------------------------


def test_publish_needs_no_consent_and_files_for_review(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    published = scenes_service.publish_scene(db, user_id=author.id, scene_id=scene.id)
    assert published.status == "pending_review"
    assert published.visibility == "public"


def test_withdraw_returns_a_published_scene_to_draft(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    scenes_service.publish_scene(db, user_id=author.id, scene_id=scene.id)
    withdrawn = scenes_service.withdraw_scene(db, user_id=author.id, scene_id=scene.id)
    assert withdrawn.status == "draft"
    assert withdrawn.visibility == "private"
