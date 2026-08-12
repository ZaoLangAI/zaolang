"""Independent keyword gates for content, learning and skill publication."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed
from app.domain.learning import service as learning
from app.domain.skill_library import service as skill_library
from app.models import LearnPost, ModerationQueueItem, User
from app.models.enums import CreationSkillCategory, LearnPostLevel
from app.platform_config import service as config_service


@pytest.fixture(autouse=True)
def _disable_log_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain import moderation_policy

    monkeypatch.setattr(moderation_policy.system_log, "emit", lambda **kwargs: None)


def test_learning_keyword_hit_creates_no_pending_post(db: Session, author: User) -> None:
    config_service.set_value(
        db,
        "learning_moderation",
        {"blocked_keywords": ["forbidden lesson"]},
        actor_user_id=None,
        note="test",
    )

    with pytest.raises(ValidationFailed, match="内容未通过安全检查"):
        learning.submit(
            db,
            author_user_id=author.id,
            title="A forbidden lesson",
            summary="summary",
            level=LearnPostLevel.BEGINNER,
            cover_asset_id=None,
            body_markdown="body",
        )

    assert db.scalar(select(func.count()).select_from(LearnPost)) == 0


def test_private_skill_is_allowed_but_blocked_before_public_queue(
    db: Session, author: User
) -> None:
    config_service.set_value(
        db,
        "skill_moderation",
        {"blocked_keywords": ["unsafe preset"]},
        actor_user_id=None,
        note="test",
    )
    skill = skill_library.create(
        db,
        owner_user_id=author.id,
        title="Private draft",
        description="description",
        category=CreationSkillCategory.OTHER,
        params_json={"prompt": "unsafe preset"},
        cover_asset_id=None,
    )

    with pytest.raises(ValidationFailed, match="内容未通过安全检查"):
        skill_library.publish(db, skill=skill, actor_user_id=author.id)

    assert db.scalar(select(func.count()).select_from(ModerationQueueItem)) == 0
