"""Feature-flag gates for the drama editor."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.errors import NotFound
from app.platform_config import service as config_service

FLAG_DRAMA = "drama_studio_enabled"
FLAG_EDITOR = "web_editor_enabled"
FLAG_EXPORT = "variant_export_enabled"
FLAG_AI = "editor_ai_enabled"
FLAG_MCP = "editor_mcp_enabled"


def require_flag(session: Session, flag: str, *, user_id: str | None = None) -> None:
    if flag in {FLAG_EXPORT, FLAG_AI, FLAG_MCP} and not config_service.is_enabled(
        session, FLAG_EDITOR, user_id=user_id
    ):
        raise NotFound("该功能暂未开放。")
    if not config_service.is_enabled(session, flag, user_id=user_id):
        raise NotFound("该功能暂未开放。")
