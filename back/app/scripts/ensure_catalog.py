"""Production-safe, additive plant of the platform-curated catalogues.

`python -m app.scripts.seed` raises when `APP_ENV=production`. This module is
the allowed production path: it never resets tables, never plants demo
accounts, and never overwrites an existing `zaolang_studio` password.

Matched by `(owner, title)` inside `ensure_catalog_skills` /
`ensure_catalog_posts`, so an operator edit to a previously planted row
survives a later re-run.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.domain.credits import service as credits_service
from app.domain.learning import service as learning_service
from app.domain.skill_library import catalog as skill_catalog
from app.domain.skill_library import service as skill_library_service
from app.models import Profile, User
from app.models.base import utcnow
from app.models.enums import Locale, Region, ThemePreference, UserRole, UserStatus
from app.security.passwords import hash_password
from app.storage import s3

logger = logging.getLogger(__name__)

STUDIO_EMAIL = "studio@zaolang.dev"
STUDIO_HANDLE = skill_catalog.CATALOG_OWNER_HANDLE
STUDIO_DISPLAY_NAME = "造浪工作室"
STUDIO_BIO = "平台精选技能策展账号：短剧创作配方合集。"


def run(*, session: Session | None = None) -> dict[str, int]:
    """Unions bucket CORS, then plants any missing catalogue rows.

    Passing `session` is for tests (they own the transaction). Production
    callers omit it and go through `session_scope`.
    """
    s3.ensure_bucket()
    if session is not None:
        return _plant(session)
    with session_scope() as owned:
        return _plant(owned)


def _plant(session: Session) -> dict[str, int]:
    owner, created = _ensure_studio_owner(session)
    skills = skill_library_service.ensure_catalog_skills(session, owner_user_id=owner.id)
    posts = learning_service.ensure_catalog_posts(session, author_user_id=owner.id)
    logger.info(
        "catalog backfill: studio_created=%s skills=%s learn_posts=%s owner=%s",
        created,
        len(skills),
        len(posts),
        owner.id,
    )
    return {
        "studio_created": int(created),
        "skills": len(skills),
        "learn_posts": len(posts),
    }


def _ensure_studio_owner(session: Session) -> tuple[User, bool]:
    """Finds `zaolang_studio` by email or handle; creates only if neither exists.

    An existing row's password is never rotated. A newly created account gets a
    random unusable password — not the local seed password.
    """
    by_email = session.scalar(select(User).where(User.email == STUDIO_EMAIL))
    by_handle = session.scalar(
        select(User).join(Profile).where(Profile.handle == STUDIO_HANDLE)
    )
    if by_email is not None and by_handle is not None and by_email.id != by_handle.id:
        raise RuntimeError(
            f"{STUDIO_EMAIL} 与 handle {STUDIO_HANDLE} 指向两个不同用户，拒绝自动合并。"
        )
    existing = by_email or by_handle
    if existing is not None:
        return existing, False

    user = User(
        email=STUDIO_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        status=UserStatus.ACTIVE,
        age_gate_confirmed_at=utcnow(),
        region=Region.CN,
        locale=Locale.ZH_CN,
        theme=ThemePreference.SYSTEM,
        roles=[UserRole.USER],
    )
    session.add(user)
    session.flush()
    session.add(
        Profile(
            user_id=user.id,
            display_name=STUDIO_DISPLAY_NAME,
            handle=STUDIO_HANDLE,
            bio=STUDIO_BIO,
        )
    )
    credits_service.get_or_create_account(session, user.id)
    session.flush()
    return user, True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    counts = run()
    print(f"目录补增完成: {counts}")


if __name__ == "__main__":
    main()
