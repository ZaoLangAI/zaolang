"""`skill_library.catalog` and `skill_library_service.ensure_catalog_skills`:
the platform-curated short-drama template catalogue `make seed` plants."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters import service as characters_service
from app.domain.scenes import service as scenes_service
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
    rows = db.scalars(select(CreationSkill).where(CreationSkill.owner_user_id == author.id)).all()
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
    rows = db.scalars(select(CreationSkill).where(CreationSkill.owner_user_id == author.id)).all()
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

    rows = db.scalars(select(CreationSkill).where(CreationSkill.owner_user_id == author.id)).all()
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


def test_covers_pending_only_names_entries_that_really_lack_one(db: Session, author: User) -> None:
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
    """`asset-*` rows are the dual-form image-asset recipes: a character or
    scene card, image operations only, and a shipped cover. The eight
    `cover_asset` rows were dropped with cover image generation (AC-8)."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    image_asset_categories = {
        CreationSkillCategory.CHARACTER,
        CreationSkillCategory.SCENE_ASSET,
    }
    items = [item for item in skill_catalog.CATALOG if item.key.startswith("asset-")]
    assert len(items) == 16
    for item in items:
        assert item.category in image_asset_categories, item.key
        assert image_ops == set(item.applicable_operations), item.key
        assert not video_ops.intersection(item.applicable_operations), item.key
        assert item.cover_path() is not None, item.key
        params = item.params_json()
        assert params["prompt_suffix"] == item.prompt_suffix
        assert params["aspect_ratio"] == item.aspect_ratio
        if item.category == CreationSkillCategory.CHARACTER:
            assert "reference_assets" not in params["character"]
        else:
            assert "reference_assets" not in params["scene"]


def test_seeded_character_and_scene_assets_get_a_reference_still(db: Session, author: User) -> None:
    """After `ensure_catalog_skills`, a character/scene recipe's cover is
    also the first reference still (the default look's sheet / master
    plate) — the plaza card and a later `@` apply share it."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    rows = db.scalars(select(CreationSkill).where(CreationSkill.owner_user_id == author.id)).all()
    asset_titles = {item.title for item in skill_catalog.CATALOG if item.key.startswith("asset-")}
    seeded = [row for row in rows if row.title in asset_titles]
    assert len(seeded) == 16
    for row in seeded:
        assert row.cover_asset_id is not None, row.title
        if row.category == CreationSkillCategory.CHARACTER:
            refs = characters_service.CharacterView(row).reference_assets
            assert refs, row.title
            assert refs[0]["asset_id"] == row.cover_asset_id
            assert refs[0]["view"] == "front"
        else:
            assert row.category == CreationSkillCategory.SCENE_ASSET
            refs = scenes_service.SceneView(row).reference_assets
            assert refs, row.title
            assert refs[0]["asset_id"] == row.cover_asset_id
            assert refs[0]["view"] == "establishing"
        # The tables are the source; the JSON above is their mirror.
        anchor = asset_variants_service.anchor(row)
        assert anchor is not None and anchor.asset_id == row.cover_asset_id, row.title
        assert anchor.variant.is_default


def test_video_only_categories_never_declare_image_operations(db: Session, author: User) -> None:
    """`lens`/`scene`/`format`/`drama`/`other` (script beats) are
    shot-composition, prompt-format, scene-playing or narrative recipes that
    don't mean anything applied to a single still — only the "图片风格 image
    style" section (still `category=STYLE`) is meant to reach
    `text_to_image`/`image_to_image`."""
    image_ops = {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
    video_only_categories = {
        CreationSkillCategory.LENS,
        CreationSkillCategory.SCENE,
        CreationSkillCategory.FORMAT,
        CreationSkillCategory.DRAMA,
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


_FORMAT_SUB_PREFIX_COUNTS = {
    "fmt-frame-": 10,
    "fmt-hook-": 10,
    "fmt-action-": 10,
    "fmt-vertical-": 10,
    "fmt-camera-": 10,
    "fmt-light-": 8,
    "fmt-audio-": 8,
    "fmt-transition-": 10,
    # The largest axis on purpose: 8 rows about *binding a reference* plus
    # 20 about holding one clip's state into the next, which is what
    # `ENHANCE_SYSTEM_PROMPT`'s beat sequence needs to stay continuous.
    "fmt-lock-": 28,
    "fmt-teaser-": 8,
    "fmt-guard-": 8,
}


def test_the_format_section_covers_every_writing_axis(db: Session, author: User) -> None:
    """The 120 `fmt-*` rows are the seeded form of
    `docs/video-prompt-formats.md`, and the eleven sub-prefixes are what keeps
    them from collapsing into "a hundred variations on one camera rule".

    Pinning the per-axis counts rather than just the total is the point: a
    later addition that quietly lands nine more camera-move rows and nothing
    about audio would still hit the total and would still be a worse
    catalogue."""
    items = [item for item in skill_catalog.CATALOG if item.key.startswith("fmt-")]

    assert len(items) == 120
    assert sum(_FORMAT_SUB_PREFIX_COUNTS.values()) == 120
    for prefix, expected in _FORMAT_SUB_PREFIX_COUNTS.items():
        found = [item for item in items if item.key.startswith(prefix)]
        assert len(found) == expected, f"{prefix} has {len(found)}, expected {expected}"
    for item in items:
        matched = [p for p in _FORMAT_SUB_PREFIX_COUNTS if item.key.startswith(p)]
        assert len(matched) == 1, f"{item.key} matches {matched}, expected exactly one axis"

    for item in items:
        assert item.category == CreationSkillCategory.FORMAT, item.key
        assert item.applicable_operations == skill_catalog._VIDEO_OPERATIONS, item.key
        assert item.aspect_ratio == "9:16", item.key
        # A rule nobody can act on is worse than no rule: every row explains
        # *why* in `description`, which is also the only field script
        # writing's `@` reference reads (see `_resolve_referenced_skills`).
        assert len(item.description) >= 40, item.key
        assert item.prompt_suffix.strip(), item.key


def test_format_prompt_suffixes_are_positive_phrasings(db: Session, author: User) -> None:
    """Runway, Luma, PixVerse and Veo all document that a negation in the
    prompt *body* biases the model toward the excluded thing — which is what
    `fmt-guard-positive-phrasing` teaches.

    `prompt_suffix` is appended straight into the outgoing prompt by
    `fold_params_prompt`, so a `fmt-*` row phrased as "no camera shake" would
    be the section contradicting its own advice on the wire. The rewrite is
    always available: state the wanted end state instead."""
    banned = {"no", "not", "never", "without", "avoid", "nothing", "neither", "nor"}
    for item in skill_catalog.CATALOG:
        if not item.key.startswith("fmt-"):
            continue
        words = {word.strip(",.:;") for word in item.prompt_suffix.lower().split()}
        offenders = words & banned
        assert not offenders, f"{item.key} uses negative phrasing: {sorted(offenders)}"


_DRAMA_SUB_PREFIX_COUNTS = {"drama-scene-": 50, "drama-emotion-": 30}


def test_the_drama_section_is_split_between_scenes_and_emotions(db: Session, author: User) -> None:
    """`drama` is the one category `app.agents.skill_matcher` searches, so
    what it contains *is* what plot matching can ever find.

    The two-way split is the substance of that: a story names a situation
    and an emotional register, and matching only one of the two would
    silently halve the feature. Pinning both counts stops a later addition
    from turning this into eighty scene types and no emotional vocabulary."""
    items = [item for item in skill_catalog.CATALOG if item.key.startswith("drama-")]

    assert len(items) == 80
    assert sum(_DRAMA_SUB_PREFIX_COUNTS.values()) == 80
    for prefix, expected in _DRAMA_SUB_PREFIX_COUNTS.items():
        found = [item for item in items if item.key.startswith(prefix)]
        assert len(found) == expected, f"{prefix} has {len(found)}, expected {expected}"

    for item in items:
        assert item.category == CreationSkillCategory.DRAMA, item.key
        assert item.applicable_operations == skill_catalog._VIDEO_OPERATIONS, item.key
        assert item.aspect_ratio == "9:16", item.key
        # `description` is the *only* field the matcher's candidate list and
        # the agents' reference block ever read (see
        # `skill_library.service.load_reference_skills`), so a thin one is a
        # row that can be matched but conveys nothing once it is.
        assert len(item.description) >= 60, item.key
        assert item.prompt_suffix.strip(), item.key


def test_drama_prompt_suffixes_are_positive_phrasings(db: Session, author: User) -> None:
    """Same rule and same reason as the `fmt-*` rows: `prompt_suffix` is
    appended straight into the outgoing prompt by `fold_params_prompt`, and
    four vendors document that a negation in the body biases the model
    toward the excluded thing.

    Enforced separately rather than by widening the `fmt-*` test so each
    section's failure names its own section."""
    banned = {"no", "not", "never", "without", "avoid", "nothing", "neither", "nor"}
    for item in skill_catalog.CATALOG:
        if not item.key.startswith("drama-"):
            continue
        words = {word.strip(",.:;") for word in item.prompt_suffix.lower().split()}
        offenders = words & banned
        assert not offenders, f"{item.key} uses negative phrasing: {sorted(offenders)}"


def test_a_seeded_format_skill_appends_its_rule_to_a_video_job(db: Session, author: User) -> None:
    """The `format` category ships through the plain `prompt_suffix` append
    path — no new folding mechanism — so this asserts a rule row behaves
    exactly like a `lens-*` recipe once seeded, only carrying a structural
    constraint instead of a look."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()

    sample = skill_catalog.find("fmt-camera-one-move")
    assert sample is not None
    row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == author.id, CreationSkill.title == sample.title
        )
    )
    assert row is not None
    assert row.category == CreationSkillCategory.FORMAT

    job = make_job(db, author, operation=Operation.TEXT_TO_VIDEO)
    ctx = WorkflowContext(
        session=db,
        job=job,
        prompt="她推开门",
        params={"prompt": "她推开门", "skill_ids": [row.id]},
        dry_run=False,
    )

    execute_skill_context(ctx, SkillContextConfig())

    # Appended, not substituted — the author's own description survives.
    assert "她推开门" in ctx.prompt
    assert sample.prompt_suffix in ctx.prompt


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


def _first_title(prefix: str) -> str:
    """The same tie-break `apply_matching_format_skills` uses (`sorted()`
    over a `frozenset`), so a test can predict which row gets picked without
    hardcoding a Chinese title that would silently go stale on a catalogue
    edit."""
    return sorted(item.title for item in skill_catalog.CATALOG if item.key.startswith(prefix))[0]


def test_apply_matching_format_skills_picks_one_row_per_weak_dimension(
    db: Session, catalog_owner: User
) -> None:
    """`camera` maps onto `fmt-camera-*`; `scene` has no `format` axis at all
    (see the mapping's own docstring) and must not match anything even when
    flagged `missing`."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[
            {"key": "camera", "status": "weak", "hint": "运镜太笼统"},
            {"key": "scene", "status": "missing", "hint": "没写场景"},
        ],
        prompt="她推开门",
        max_length=4096,
    )

    assert len(applied) == 1
    expected_title = _first_title("fmt-camera-")
    assert applied[0]["title"] == expected_title
    expected_row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == catalog_owner.id,
            CreationSkill.title == expected_title,
        )
    )
    assert expected_row is not None
    assert applied[0]["id"] == expected_row.id
    assert "她推开门" in prompt
    assert expected_row.params_json["prompt_suffix"] in prompt


def test_apply_matching_format_skills_respects_the_dimension_order_and_limit(
    db: Session, catalog_owner: User
) -> None:
    """At most `MAX_AUTO_APPLIED_FORMAT_SKILLS`, taken in the diagnosis's own
    dimension order — not every matching dimension gets a row once the cap
    is hit."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    _prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[
            {"key": "subject", "status": "missing", "hint": "x"},
            {"key": "action", "status": "weak", "hint": "x"},
            {"key": "camera", "status": "weak", "hint": "x"},
        ],
        prompt="她推开门",
        max_length=4096,
    )

    assert skill_library_service.MAX_AUTO_APPLIED_FORMAT_SKILLS == 2
    assert [item["title"] for item in applied] == [
        _first_title("fmt-frame-"),
        _first_title("fmt-action-"),
    ]


def test_apply_matching_format_skills_is_a_noop_for_an_image_operation(
    db: Session, catalog_owner: User
) -> None:
    """Every seeded `format` row is video-only — an image polish must never
    pick one up even when a (hypothetical) dimension name collides."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_image",
        dimensions=[{"key": "camera", "status": "missing", "hint": "x"}],
        prompt="她推开门",
        max_length=4096,
    )

    assert applied == []
    assert prompt == "她推开门"


def test_apply_matching_format_skills_never_exceeds_max_length(
    db: Session, catalog_owner: User
) -> None:
    """Appending is skipped rather than truncating a rule mid-sentence."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[{"key": "camera", "status": "weak", "hint": "x"}],
        prompt="她推开门",
        max_length=len("她推开门"),
    )

    assert applied == []
    assert prompt == "她推开门"


def test_apply_matching_format_skills_skips_a_suffix_already_in_the_prompt(
    db: Session, catalog_owner: User
) -> None:
    """A rule already spelled out by the author (or a previous round) is not
    appended twice — the picker falls through to the next `fmt-camera-*` row
    for that same dimension instead, since the dimension is still weak."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    first_title = _first_title("fmt-camera-")
    first_row = db.scalar(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == catalog_owner.id,
            CreationSkill.title == first_title,
        )
    )
    assert first_row is not None
    suffix = first_row.params_json["prompt_suffix"]

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[{"key": "camera", "status": "weak", "hint": "x"}],
        prompt=f"她推开门，{suffix}",
        max_length=4096,
    )

    assert first_row.id not in {item["id"] for item in applied}
    assert suffix in prompt
    # `prompt.count` rather than `in`: the point is it was not appended a
    # second time, not that it is absent.
    assert prompt.count(suffix) == 1


def test_apply_matching_format_skills_gives_up_on_a_dimension_once_every_row_is_used(
    db: Session, catalog_owner: User
) -> None:
    """Once every `fmt-camera-*` row's suffix is already on the wire, the
    dimension contributes nothing rather than erroring or looping."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    camera_titles = [
        item.title for item in skill_catalog.CATALOG if item.key.startswith("fmt-camera-")
    ]
    camera_rows = db.scalars(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == catalog_owner.id,
            CreationSkill.title.in_(camera_titles),
        )
    ).all()
    assert camera_rows
    already_present = "，".join(row.params_json["prompt_suffix"] for row in camera_rows)

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[{"key": "camera", "status": "weak", "hint": "x"}],
        prompt=f"她推开门，{already_present}",
        max_length=8192,
    )

    assert applied == []
    assert prompt == f"她推开门，{already_present}"


def test_apply_matching_format_skills_ignores_a_users_skill_under_a_catalogue_title(
    db: Session, author: User, catalog_owner: User
) -> None:
    """Auto-apply skips unlock and usage, so it may only pick planted rows. A
    user's published — and here paid — `format` skill that borrows a
    catalogue title must neither be applied for free when the catalogue is
    missing nor shadow the planted row once it is there."""
    title = _first_title("fmt-camera-")
    impostor = CreationSkill(
        owner_user_id=author.id,
        title=title,
        category=CreationSkillCategory.FORMAT,
        params_json={"prompt_suffix": "付费运镜秘籍"},
        applicable_operations_json=[Operation.TEXT_TO_VIDEO.value],
        visibility=CreationSkillVisibility.PUBLIC,
        status=CreationSkillStatus.PUBLISHED,
        access_credits=50,
    )
    db.add(impostor)
    db.commit()
    dimensions = [{"key": "camera", "status": "weak", "hint": "x"}]

    prompt, applied = skill_library_service.apply_matching_format_skills(
        db, operation="text_to_video", dimensions=dimensions, prompt="她推开门", max_length=4096
    )
    assert applied == []
    assert prompt == "她推开门"

    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()
    prompt, applied = skill_library_service.apply_matching_format_skills(
        db, operation="text_to_video", dimensions=dimensions, prompt="她推开门", max_length=4096
    )
    assert [entry["title"] for entry in applied] == [title]
    assert applied[0]["id"] != impostor.id
    assert "付费运镜秘籍" not in prompt


def test_apply_matching_format_skills_skips_a_planted_row_an_operator_priced(
    db: Session, catalog_owner: User
) -> None:
    """Free is what makes skipping unlock defensible — a planted row that
    later gets a price drops out of auto-apply."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    camera_titles = [
        item.title for item in skill_catalog.CATALOG if item.key.startswith("fmt-camera-")
    ]
    for row in db.scalars(
        select(CreationSkill).where(
            CreationSkill.owner_user_id == catalog_owner.id,
            CreationSkill.title.in_(camera_titles),
        )
    ):
        row.access_credits = 10
    db.commit()

    _prompt, applied = skill_library_service.apply_matching_format_skills(
        db,
        operation="text_to_video",
        dimensions=[{"key": "camera", "status": "weak", "hint": "x"}],
        prompt="她推开门",
        max_length=4096,
    )

    assert applied == []
