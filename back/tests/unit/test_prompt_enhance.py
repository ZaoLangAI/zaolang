"""`app.domain.prompts.enhance`: detail-level assessment shared by the
shortform studio and the generation studio's own polish button."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain import prompts
from app.domain.errors import ValidationFailed
from app.models import User
from tests.llm_catalog import bind_default_agents_to_catalog


@pytest.fixture(autouse=True)
def _bind_copy_model(db: Session) -> None:
    bind_default_agents_to_catalog(db)


def test_a_sparse_description_is_flagged_and_expanded(db: Session, author: User) -> None:
    result = prompts.enhance(db, user_id=author.id, prompt="女孩在海边")
    assert result.detail_level == "sparse"
    assert result.feedback
    assert result.prompt != "女孩在海边"
    assert result.degraded is False


def test_an_already_detailed_description_is_barely_touched(db: Session, author: User) -> None:
    text = (
        "黄昏时分，一位穿着白色长裙的女孩独自站在海边礁石上，海风吹动她的裙摆，"
        "镜头缓慢从远景推近到她的侧脸特写，逆光剪影，暖橙色调，长焦压缩景深"
    )
    result = prompts.enhance(db, user_id=author.id, prompt=text)
    assert result.detail_level == "detailed"
    assert result.prompt == text


def test_blank_input_is_rejected_before_calling_the_agent(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        prompts.enhance(db, user_id=author.id, prompt="   ")
