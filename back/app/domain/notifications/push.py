"""站内通知落库 + APNs 推送派发的统一入口。

本地/测试环境没有真实 APNs Key（`.p8` + Team ID + Key ID），`send_push` 只打日志占位，
接口契约与调用点已经就位——接真实 APNs 只需要替换这一个函数的函数体，换成
`aioapns`/`httpx` 直连 `api.push.apple.com` 的 HTTP/2 请求，调用点不用动。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, Notification
from app.models.enums import NotificationType

logger = logging.getLogger(__name__)


def notify(
    session: Session,
    *,
    user_id: str,
    type: NotificationType,
    title_key: str,
    payload: dict[str, Any] | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> Notification:
    """写一行站内通知，并尽力推一次 APNs。调用方负责在这之前/之后自己 commit——
    这里不 commit，避免和调用方已经开着的事务打架（例如任务状态机的 `_emit`）。
    """
    record = Notification(
        user_id=user_id,
        type=type,
        title_key=title_key,
        payload_json=payload or {},
        target_type=target_type,
        target_id=target_id,
    )
    session.add(record)
    session.flush()
    _dispatch_push(session, user_id=user_id, title_key=title_key, payload=payload or {})
    return record


def _dispatch_push(
    session: Session, *, user_id: str, title_key: str, payload: dict[str, Any]
) -> None:
    tokens = session.scalars(select(Device.push_token).where(Device.user_id == user_id)).all()
    for token in tokens:
        send_push(token, title_key=title_key, payload=payload)


def send_push(push_token: str, *, title_key: str, payload: dict[str, Any]) -> None:
    """真正打进 APNs 的那一下。当前是占位实现——生产环境要换成真实 HTTP/2 请求。"""
    logger.info("push_stub token=%s title_key=%s payload=%s", push_token, title_key, payload)
