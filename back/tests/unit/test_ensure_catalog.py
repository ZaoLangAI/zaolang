"""`app.scripts.ensure_catalog` is the production-allowed catalogue backfill.

`app.scripts.seed` stays refused when `APP_ENV=production`. This module only
plants missing `CreationSkill` / `LearnPost` rows and default workflow
templates, and never rotates an existing `zaolang_studio` password.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.learning import catalog as learning_catalog
from app.domain.skill_library import catalog as skill_catalog
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import CreationSkill, GenerationWorkflowTemplate, LearnPost, Profile, User
from app.models.enums import ImageAssetKind
from app.scripts import ensure_catalog
from app.scripts.seed import SEED_PASSWORD
from app.scripts.seed import run as seed_run
from app.security.passwords import verify_password
from tests.conftest import make_user


@pytest.fixture
def _quiet_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ensure_catalog.s3, "ensure_bucket", lambda: None)


def test_seed_run_raises_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production", raising=False)
    with pytest.raises(RuntimeError, match="拒绝在生产环境"):
        seed_run()


def test_ensure_catalog_is_allowed_in_production(
    db: Session, _quiet_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production", raising=False)
    counts = ensure_catalog.run(session=db)
    assert counts["studio_created"] == 1
    assert counts["skills"] == len(skill_catalog.CATALOG)
    assert counts["learn_posts"] == len(learning_catalog.CATALOG)


def test_ensure_catalog_plants_the_catalogues_for_a_new_studio(
    db: Session, _quiet_bucket: None
) -> None:
    counts = ensure_catalog.run(session=db)
    assert counts["studio_created"] == 1

    owner = db.scalar(select(User).where(User.email == ensure_catalog.STUDIO_EMAIL))
    assert owner is not None
    assert not verify_password(SEED_PASSWORD, owner.password_hash)
    profile = db.scalar(select(Profile).where(Profile.user_id == owner.id))
    assert profile is not None
    assert profile.handle == ensure_catalog.STUDIO_HANDLE

    skills = db.scalars(select(CreationSkill).where(CreationSkill.owner_user_id == owner.id)).all()
    posts = db.scalars(select(LearnPost).where(LearnPost.author_user_id == owner.id)).all()
    assert len(skills) == len(skill_catalog.CATALOG)
    assert len(posts) == len(learning_catalog.CATALOG)


def test_ensure_catalog_does_not_rotate_an_existing_studio_password(
    db: Session, _quiet_bucket: None
) -> None:
    studio = make_user(
        db,
        email=ensure_catalog.STUDIO_EMAIL,
        handle=ensure_catalog.STUDIO_HANDLE,
        display_name=ensure_catalog.STUDIO_DISPLAY_NAME,
    )
    original_hash = studio.password_hash

    first = ensure_catalog.run(session=db)
    second = ensure_catalog.run(session=db)

    db.refresh(studio)
    assert studio.password_hash == original_hash
    assert first["studio_created"] == 0
    assert first["skills"] == len(skill_catalog.CATALOG)
    assert first["learn_posts"] == len(learning_catalog.CATALOG)
    assert second == {
        "studio_created": 0,
        "skills": 0,
        "learn_posts": 0,
        "workflow_templates": 0,
        "agents": 0,
    }


def test_ensure_catalog_publishes_a_missing_asset_kind_template(
    db: Session, _quiet_bucket: None
) -> None:
    ensure_catalog.run(session=db)
    prop = db.scalar(
        select(GenerationWorkflowTemplate).where(
            GenerationWorkflowTemplate.operation == "text_to_image",
            GenerationWorkflowTemplate.asset_kind == ImageAssetKind.PROP.value,
            GenerationWorkflowTemplate.is_active.is_(True),
        )
    )
    assert prop is not None
    db.delete(prop)
    db.flush()

    counts = ensure_catalog.run(session=db)

    assert counts["workflow_templates"] == 1
    restored = workflow_templates_service.get_active(db, "text_to_image", ImageAssetKind.PROP.value)
    assert restored is not None
    assert restored.asset_kind == ImageAssetKind.PROP.value


def test_ensure_catalog_refuses_a_split_studio_identity(db: Session, _quiet_bucket: None) -> None:
    make_user(db, email=ensure_catalog.STUDIO_EMAIL, handle="not-studio")
    make_user(db, email="other-studio@zaolang.dev", handle=ensure_catalog.STUDIO_HANDLE)

    with pytest.raises(RuntimeError, match=ensure_catalog.STUDIO_HANDLE):
        ensure_catalog.run(session=db)
