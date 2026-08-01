"""Shared back-office dependencies.

Rank aliases keep the intent readable at each route: a reviewer can decide
content, an operator can move money and jobs, an admin can change platform
configuration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api import rate_limit
from app.api.deps import get_admin_user, require_admin_role
from app.domain.errors import ValidationFailed
from app.models import User

Viewer = Annotated[User, Depends(require_admin_role("viewer"))]
Reviewer = Annotated[User, Depends(require_admin_role("reviewer"))]
Operator = Annotated[User, Depends(require_admin_role("operator"))]
Admin = Annotated[User, Depends(require_admin_role("admin"))]


def admin_rate_limited(bucket: str):  # type: ignore[no-untyped-def]
    def _dependency(user: Annotated[User, Depends(get_admin_user)]) -> None:
        rate_limit.enforce(bucket, f"admin:{user.id}")

    return _dependency


AdminRead = Annotated[None, Depends(admin_rate_limited("admin_read"))]
AdminWrite = Annotated[None, Depends(admin_rate_limited("admin_write"))]
AdminDangerous = Annotated[None, Depends(admin_rate_limited("admin_dangerous"))]


def require_confirmation(confirmed: bool) -> None:
    """Second gate for irreversible actions.

    The reason is enforced by the schema; this checks the operator explicitly
    acknowledged the consequence rather than submitting a form by reflex.
    """
    if not confirmed:
        raise ValidationFailed("高危操作需要二次确认。", fields={"confirm": "必须为 true"})


def request_context(request: Request) -> Request:
    return request


RequestContext = Annotated[Request, Depends(request_context)]
