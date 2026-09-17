"""`skill_context` folds style-gallery and creation-skill templates into a job."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.skill_library import service as skill_library
from app.domain.style_gallery import service as style_gallery
from app.models import User
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    Operation,
)
from app.workflows.configs import SkillContextConfig
from app.workflows.nodes import execute_skill_context
from app.workflows.types import WorkflowContext
from tests.factories import make_job


def _style(
    db: Session,
    *,
    slug: str = "anime-japanese",
    params_json: dict | None = None,
    is_active: bool = True,
):
    entry = style_gallery.create(
        db,
        slug=slug,
        label_zh="日漫",
        label_en="Japanese anime",
        label_ja="日本アニメ",
        description="赛璐璐渲染。",
        cover_asset_id=None,
        params_json=params_json
        or {"aspect_ratio": "9:16", "prompt_suffix": "japanese anime style"},
        sort_order=0,
    )
    if not is_active:
        style_gallery.update(
            db,
            entry=entry,
            label_zh=entry.label_zh,
            label_en=entry.label_en,
            label_ja=entry.label_ja,
            description=entry.description,
            cover_asset_id=None,
            params_json=entry.params_json,
            sort_order=entry.sort_order,
            is_active=False,
        )
    return entry


def _ctx(
    db: Session,
    author: User,
    *,
    prompt: str = "海边的黄昏",
    params: dict | None = None,
    dry_run: bool = False,
    operation: str = Operation.TEXT_TO_IMAGE,
) -> WorkflowContext:
    job = make_job(db, author, operation=operation)
    return WorkflowContext(
        session=db,
        job=job,
        prompt=prompt,
        params=params or {"prompt": prompt, "aspect_ratio": "16:9"},
        dry_run=dry_run,
    )


def test_style_gallery_suffix_is_folded_when_absent_from_the_prompt(
    db: Session, author: User
) -> None:
    entry = _style(db)
    ctx = _ctx(db, author, params={"prompt": "海边的黄昏", "style_gallery_id": entry.id})
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏，japanese anime style"
    assert "style_gallery_id" not in ctx.params


def test_style_gallery_suffix_is_not_duplicated_when_already_in_the_prompt(
    db: Session, author: User
) -> None:
    entry = _style(db)
    ctx = _ctx(
        db,
        author,
        prompt="海边的黄昏，japanese anime style",
        params={
            "prompt": "海边的黄昏，japanese anime style",
            "style_gallery_id": entry.id,
        },
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏，japanese anime style"


def test_a_disabled_style_gallery_entry_is_skipped(db: Session, author: User) -> None:
    entry = _style(db, is_active=False)
    ctx = _ctx(db, author, params={"prompt": "海边的黄昏", "style_gallery_id": entry.id})
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏"


def test_skills_fold_after_the_style_gallery_entry(db: Session, author: User) -> None:
    entry = _style(db)
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="胶片",
        description="",
        category=CreationSkillCategory.LENS,
        params_json={"prompt_suffix": "35mm film grain"},
        cover_asset_id=None,
    )
    ctx = _ctx(
        db,
        author,
        params={
            "prompt": "海边的黄昏",
            "style_gallery_id": entry.id,
            "skill_ids": [skill.id],
        },
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏，japanese anime style，35mm film grain"


def test_none_user_negative_prompt_does_not_wipe_the_template(db: Session, author: User) -> None:
    entry = _style(
        db,
        params_json={
            "prompt_suffix": "japanese anime style",
            "negative_prompt": "watermark, text",
        },
    )
    ctx = _ctx(
        db,
        author,
        params={
            "prompt": "海边的黄昏",
            "negative_prompt": None,
            "style_gallery_id": entry.id,
        },
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.params["negative_prompt"] == "watermark, text"


def test_the_users_negative_prompt_wins_over_the_template(db: Session, author: User) -> None:
    entry = _style(
        db,
        params_json={
            "prompt_suffix": "japanese anime style",
            "negative_prompt": "watermark, text",
        },
    )
    ctx = _ctx(
        db,
        author,
        params={
            "prompt": "海边的黄昏",
            "negative_prompt": "extra fingers",
            "style_gallery_id": entry.id,
        },
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.params["negative_prompt"] == "extra fingers"


def test_a_locked_paid_skill_is_not_folded(db: Session, author: User, remixer: User) -> None:
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="付费胶片",
        description="",
        category=CreationSkillCategory.LENS,
        params_json={"prompt_suffix": "35mm film grain"},
        cover_asset_id=None,
        access_credits=8,
    )
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()

    ctx = _ctx(
        db,
        remixer,
        params={"prompt": "海边的黄昏", "skill_ids": [skill.id]},
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏"


def test_a_character_skill_with_prompt_suffix_folds_into_text_to_image(
    db: Session, author: User
) -> None:
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="三视图设定板",
        description="原创人设",
        category=CreationSkillCategory.CHARACTER,
        params_json={
            "prompt_suffix": "left-to-right turnaround sheet, no readable text",
            "aspect_ratio": "3:4",
            "character": {
                "description": "原创人设",
                "reference_assets": [{"asset_id": "ast_demo", "view": "front"}],
            },
        },
        cover_asset_id=None,
        applicable_operations=[Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE],
    )
    ctx = _ctx(db, author, params={"prompt": "海边的黄昏", "skill_ids": [skill.id]})
    execute_skill_context(ctx, SkillContextConfig())
    assert "left-to-right turnaround sheet" in ctx.prompt
    assert ctx.params["aspect_ratio"] == "3:4"
    assert "character" not in ctx.params


def test_a_user_character_without_flat_keys_is_skipped(db: Session, author: User) -> None:
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="我的角色",
        description="",
        category=CreationSkillCategory.CHARACTER,
        params_json={"character": {"description": "我的 OC", "reference_assets": []}},
        cover_asset_id=None,
    )
    ctx = _ctx(db, author, params={"prompt": "海边的黄昏", "skill_ids": [skill.id]})
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏"
    assert "character" not in ctx.params


def test_dry_run_does_not_fold_style_or_skills(db: Session, author: User) -> None:
    entry = _style(db)
    ctx = _ctx(
        db,
        author,
        params={"prompt": "海边的黄昏", "style_gallery_id": entry.id},
        dry_run=True,
    )
    execute_skill_context(ctx, SkillContextConfig())
    assert ctx.prompt == "海边的黄昏"


def test_a_workflow_skills_variables_never_reach_the_params(db: Session, author: User) -> None:
    """The single data-leak surface of creation workflows.

    `params_json` is folded wholesale for a template skill, so a workflow's
    `variables` — the question list its author wrote for the form — would ride
    straight into `ctx.params` and out to the provider. The answers belong in
    the prompt; the questions belong nowhere near the request.
    """
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="打光工作流",
        description="",
        category=CreationSkillCategory.STYLE,
        params_json={
            "prompt_suffix": "single hard key light",
            "variables": [
                {
                    "id": "mood",
                    "kind": "single_choice",
                    "prompt": "想要什么情绪",
                    "options": [{"value": "cold", "label": "冷"}],
                    "required": True,
                }
            ],
        },
        cover_asset_id=None,
    )
    ctx = _ctx(db, author, params={"prompt": "海边的黄昏", "skill_ids": [skill.id]})
    execute_skill_context(ctx, SkillContextConfig())

    assert "variables" not in ctx.params
    # The rest of the recipe still folds — the guard is a key filter, not a
    # reason to skip the skill.
    assert ctx.prompt == "海边的黄昏，single hard key light"
