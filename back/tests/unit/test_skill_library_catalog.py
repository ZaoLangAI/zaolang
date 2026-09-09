"""`skill_library.catalog` and `skill_library_service.ensure_catalog_skills`:
the platform-curated short-drama template catalogue `make seed` plants."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.skill_library import catalog as skill_catalog
from app.domain.skill_library import service as skill_library_service
from app.models import Asset, CreationSkill, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    MediaType,
    Operation,
)
from app.workflows.configs import SkillContextConfig
from app.workflows.nodes import execute_skill_context
from app.workflows.types import WorkflowContext
from tests.factories import make_job


def test_ensure_catalog_skills_plants_the_whole_catalogue(db: Session, author: User) -> None:
    created = skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    assert len(created) == len(skill_catalog.CATALOG)
    rows = db.scalars(
        select(CreationSkill).where(CreationSkill.owner_user_id == author.id)
    ).all()
    assert len(rows) == len(skill_catalog.CATALOG)
    for row in rows:
        assert row.status == CreationSkillStatus.PUBLISHED
        assert row.visibility == CreationSkillVisibility.PUBLIC
        assert row.access_credits == 0
        assert row.reviewed_by_user_id is None
        assert row.reviewed_at is None


def test_ensure_catalog_skills_is_idempotent(db: Session, author: User) -> None:
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    second_run = skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    assert second_run == []
    rows = db.scalars(
        select(CreationSkill).where(CreationSkill.owner_user_id == author.id)
    ).all()
    assert len(rows) == len(skill_catalog.CATALOG)


def test_ensure_catalog_skills_does_not_overwrite_an_operator_edit(
    db: Session, author: User
) -> None:
    """A title already present for this owner is left alone — an operator's
    hand-edit to a previously-seeded row must survive a later `make seed`."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample = skill_catalog.CATALOG[0]
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None
    row.description = "运营改过的文案"
    db.commit()

    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    db.expire_all()
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None
    assert row.description == "运营改过的文案"


def test_ensure_catalog_skills_backfills_a_cover_for_every_entry(db: Session, author: User) -> None:
    """Every catalogue entry ships a `seed_covers/<key>.jpg` — see
    `CatalogSkill.cover_path`. `ensure_catalog_skills` must attach one to
    every seeded row's `cover_asset_id`, not leave the marketplace grid
    covers empty."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    rows = db.scalars(
        select(CreationSkill).where(CreationSkill.owner_user_id == author.id)
    ).all()
    assert len(rows) == len(skill_catalog.CATALOG)
    for row in rows:
        item = next(entry for entry in skill_catalog.CATALOG if entry.title == row.title)
        if item.key in skill_catalog.COVERS_PENDING:
            # Awaiting a generated still — see `COVERS_PENDING`. Enumerated in
            # the catalogue rather than skipped by a rule, so the gap cannot
            # grow silently.
            continue
        assert item.cover_path() is not None, f"{item.key} shipped with no cover"
        assert row.cover_asset_id is not None, f"{row.title} has no cover_asset_id"


def test_covers_pending_only_names_entries_that_really_lack_one(
    db: Session, author: User
) -> None:
    """`COVERS_PENDING` is a to-do list, not a mute button: a key stays on it
    only until its JPEG lands, and it may not name an entry that is not in the
    catalogue at all."""
    keys = {entry.key for entry in skill_catalog.CATALOG}
    assert keys >= skill_catalog.COVERS_PENDING
    for key in skill_catalog.COVERS_PENDING:
        entry = skill_catalog.find(key)
        assert entry is not None
        assert entry.cover_path() is None, f"{key} has a cover now — drop it from COVERS_PENDING"


def test_ensure_catalog_skills_does_not_overwrite_an_operators_cover(
    db: Session, author: User
) -> None:
    """A cover already set — from an earlier backfill or an operator's own
    re-cover in the admin console — is never replaced by a later `make
    seed`."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample_title = skill_catalog.CATALOG[0].title
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample_title
        )
    )
    assert row is not None
    original_cover_asset_id = row.cover_asset_id
    assert original_cover_asset_id is not None
    replacement = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1,
        checksum_sha256="0" * 64,
        role=AssetRole.COVER,
    )
    db.add(replacement)
    db.flush()
    row.cover_asset_id = replacement.id
    db.commit()

    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    db.expire_all()
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample_title
        )
    )
    assert row is not None
    assert row.cover_asset_id == replacement.id


def test_asset_catalog_entries_are_image_only_recipes() -> None:
    """`asset-*` rows are the dual-form image-asset recipes: one of the
    three plaza buckets, image operations only, and a shipped cover."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    image_asset_categories = {
        CreationSkillCategory.CHARACTER,
        CreationSkillCategory.SCENE_ASSET,
        CreationSkillCategory.COVER_ASSET,
    }
    items = [item for item in skill_catalog.CATALOG if item.key.startswith("asset-")]
    assert len(items) == 24
    for item in items:
        assert item.category in image_asset_categories, item.key
        assert image_ops == set(item.applicable_operations), item.key
        assert not video_ops.intersection(item.applicable_operations), item.key
        assert item.cover_path() is not None, item.key
        params = item.params_json()
        assert params["prompt_suffix"] == item.prompt_suffix
        assert params["aspect_ratio"] == item.aspect_ratio
        if item.category == CreationSkillCategory.CHARACTER:
            assert params["character"]["reference_assets"] == []
        elif item.category == CreationSkillCategory.SCENE_ASSET:
            assert params["scene"]["reference_assets"] == []
        else:
            assert "character" not in params
            assert "scene" not in params


def test_seeded_character_and_scene_assets_get_a_reference_still(
    db: Session, author: User
) -> None:
    """After `ensure_catalog_skills`, a character/scene recipe's cover is
    also the first `reference_assets` still — the plaza card and a later
    `@` apply share it."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    rows = db.scalars(
        select(CreationSkill).where(CreationSkill.owner_user_id == author.id)
    ).all()
    asset_titles = {
        item.title for item in skill_catalog.CATALOG if item.key.startswith("asset-")
    }
    seeded = [row for row in rows if row.title in asset_titles]
    assert len(seeded) == 24
    for row in seeded:
        assert row.cover_asset_id is not None, row.title
        if row.category == CreationSkillCategory.CHARACTER:
            refs = (row.params_json.get("character") or {}).get("reference_assets") or []
            assert refs, row.title
            assert refs[0]["asset_id"] == row.cover_asset_id
            assert refs[0]["view"] == "front"
        elif row.category == CreationSkillCategory.SCENE_ASSET:
            refs = (row.params_json.get("scene") or {}).get("reference_assets") or []
            assert refs, row.title
            assert refs[0]["asset_id"] == row.cover_asset_id
            assert refs[0]["view"] == "establishing"
        else:
            assert row.category == CreationSkillCategory.COVER_ASSET
            assert "character" not in (row.params_json or {})
            assert "scene" not in (row.params_json or {})


def test_video_only_categories_never_declare_image_operations(db: Session, author: User) -> None:
    """`lens`/`scene`/`other` (script beats) are shot-composition or
    narrative recipes that don't mean anything applied to a single still —
    only the "图片风格 image style" section (still `category=STYLE`) is
    meant to reach `text_to_image`/`image_to_image`."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_only_categories = {
        CreationSkillCategory.LENS,
        CreationSkillCategory.SCENE,
        CreationSkillCategory.OTHER,
    }
    for item in skill_catalog.CATALOG:
        if item.key.startswith(skill_catalog.CANVAS_STILL_KEY_PREFIXES):
            continue
        if item.category in video_only_categories:
            assert not image_ops.intersection(item.applicable_operations), item.key


def test_canvas_still_entries_declare_only_image_operations(db: Session, author: User) -> None:
    """The canvas still section is the second carve-out, and it is a narrow
    one: a camera *move* still means nothing on a single frame, but framing,
    staging and method do. Scoped by key prefix exactly like the image-style
    section, so relaxing the rule for these cannot quietly relax it for
    `lens-oner-continuous` too.

    They must declare image operations and only image operations — an entry
    that leaked into the video studio's `@` menu would tell a video model to
    hold a still frame."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    items = [
        item
        for item in skill_catalog.CATALOG
        if item.key.startswith(skill_catalog.CANVAS_STILL_KEY_PREFIXES)
    ]

    assert len(items) >= 20
    for item in items:
        assert image_ops.issubset(set(item.applicable_operations)), item.key
        assert not video_ops.intersection(item.applicable_operations), item.key


def test_image_style_entries_declare_only_image_operations(db: Session, author: User) -> None:
    """The `image-*` catalogue keys are the deliberate exception carved out
    of `test_video_only_categories_never_declare_image_operations` — they
    must actually reach the image studio's `@` menu and stay out of the
    video one."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    image_style_items = [item for item in skill_catalog.CATALOG if item.key.startswith("image-")]

    assert len(image_style_items) >= 10
    for item in image_style_items:
        assert item.category == CreationSkillCategory.STYLE, item.key
        assert image_ops.issubset(set(item.applicable_operations)), item.key
        assert not video_ops.intersection(item.applicable_operations), item.key


def test_a_seeded_lens_skill_folds_its_prompt_suffix_into_the_job(
    db: Session, author: User
) -> None:
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample = skill_catalog.find("lens-extreme-closeup-reveal")
    assert sample is not None
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None

    job = make_job(db, author, operation=Operation.TEXT_TO_VIDEO)
    ctx = WorkflowContext(
        session=db,
        job=job,
        prompt="霓虹雨夜",
        params={"prompt": "霓虹雨夜", "skill_ids": [row.id]},
        dry_run=False,
    )

    execute_skill_context(ctx, SkillContextConfig())

    assert sample.prompt_suffix in ctx.prompt
    assert ctx.params["prompt_suffix"] == sample.prompt_suffix


def test_a_seeded_image_style_skill_folds_its_prompt_suffix_into_an_image_job(
    db: Session, author: User
) -> None:
    """Mirrors `test_a_seeded_lens_skill_folds_its_prompt_suffix_into_the_job`
    but for `Operation.TEXT_TO_IMAGE` — the whole point of the `image-*`
    section is that it actually reaches an image job, unlike the video-only
    categories."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample = skill_catalog.find("image-figurine-blindbox")
    assert sample is not None
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None

    job = make_job(db, author, operation=Operation.TEXT_TO_IMAGE)
    ctx = WorkflowContext(
        session=db,
        job=job,
        prompt="一张全身照",
        params={"prompt": "一张全身照", "skill_ids": [row.id]},
        dry_run=False,
    )

    execute_skill_context(ctx, SkillContextConfig())

    assert sample.prompt_suffix in ctx.prompt
    assert ctx.params["prompt_suffix"] == sample.prompt_suffix
    assert ctx.params["aspect_ratio"] == sample.aspect_ratio


def test_a_seeded_beat_skill_is_usable_as_a_script_style_reference(
    db: Session, author: User
) -> None:
    """The `other`-category "script beat" skills are consumed through
    `title`/`description` only (`script_writing.service
    ._resolve_referenced_skills`) — this asserts they at least clear the same
    usability gate that helper checks (`get_usable` + unlocked)."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample = skill_catalog.find("beat-three-second-hook")
    assert sample is not None
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None
    assert row.category == CreationSkillCategory.OTHER
    assert row.description == sample.description

    usable = skill_library_service.get_usable(db, skill_id=row.id, viewer_id=None)
    assert usable.id == row.id
    assert skill_library_service.viewer_has_access(db, usable, None) is True
