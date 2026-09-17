"""Shared keyword gates for independently owned moderation domains."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed
from app.domain.system_log import service as system_log
from app.models.enums import SystemLogSource
from app.platform_config import service as config_service
from app.platform_config.schemas import KeywordModerationConfig

SAFE_REJECTION_MESSAGE = "内容未通过安全检查，请调整后重试。"


def match_blocked_keyword(texts: Iterable[str], keywords: Iterable[str]) -> bool:
    haystack = "\n".join(texts).casefold()
    return any(keyword.casefold() in haystack for keyword in keywords if keyword)


def assert_allowed(
    session: Session,
    *,
    config_key: str,
    texts: Iterable[str],
    user_id: str | None = None,
    subject_type: str,
) -> None:
    config = config_service.get_typed(session, config_key, KeywordModerationConfig)
    if not match_blocked_keyword(texts, config.blocked_keywords):
        return
    record_block_signal(config_key=config_key, subject_type=subject_type, user_id=user_id)
    raise ValidationFailed(SAFE_REJECTION_MESSAGE, reason_code="PROHIBITED_CONTENT")


def record_block_signal(*, config_key: str, subject_type: str, user_id: str | None = None) -> None:
    system_log.emit(
        source=SystemLogSource.MODERATION,
        event="keyword_blocked",
        message="A submission was blocked by a configured moderation rule.",
        dedup_key=f"{config_key}:{subject_type}",
        user_id=user_id,
        details={"config_key": config_key, "subject_type": subject_type},
    )


def text_values(value: Any) -> list[str]:
    """All textual leaves in a JSON-compatible parameter object."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for child in value.values():
            result.extend(text_values(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(text_values(child))
        return result
    return []
