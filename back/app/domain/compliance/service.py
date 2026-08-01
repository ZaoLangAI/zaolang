"""Data subject rights.

Export gathers everything the platform holds about one account. Erasure is
deliberately *not* a delete: descendants of a user's work must still be able to
resolve their ancestry, so the account is anonymised and its works become
tombstones while the lineage edges survive.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound
from app.models import (
    Asset,
    Bookmark,
    CreditAccount,
    CreditLedgerEntry,
    Draft,
    Follow,
    GenerationJob,
    Like,
    Profile,
    User,
    Work,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import LifecycleStatus, UserStatus, Visibility
from app.storage import s3

logger = logging.getLogger(__name__)

EXPORT_PREFIX = "exports/users"
ANONYMISED_DOMAIN = "deleted.zaolang.invalid"


def export_user_data(session: Session, user_id: str) -> str:
    """Writes a JSON bundle to object storage and returns its key.

    The bundle is placed under a random suffix and served only through a signed
    URL, so possession of the key alone does not grant access.
    """
    user = session.get(User, user_id)
    if user is None:
        raise NotFound("用户不存在。")

    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))

    bundle = {
        "exported_at": utcnow().isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "region": user.region,
            "locale": user.locale,
            "theme": user.theme,
            "created_at": user.created_at.isoformat(),
        },
        "profile": _profile_payload(profile),
        "works": _works_payload(session, user_id),
        "drafts": [
            {
                "id": d.id,
                "title": d.title,
                "params": d.params_json,
                "created_at": d.created_at.isoformat(),
            }
            for d in session.scalars(select(Draft).where(Draft.user_id == user_id))
        ],
        "generation_jobs": [
            {
                "id": j.id,
                "operation": j.operation,
                "status": j.status,
                "quoted_credits": j.quoted_credits,
                "actual_credits": j.actual_credits,
                "created_at": j.created_at.isoformat(),
            }
            for j in session.scalars(select(GenerationJob).where(GenerationJob.user_id == user_id))
        ],
        "credits": _credits_payload(session, account),
        "assets": [
            {
                "id": a.id,
                "media_type": a.media_type,
                "size_bytes": a.size_bytes,
                "role": a.role,
                "created_at": a.created_at.isoformat(),
            }
            for a in session.scalars(select(Asset).where(Asset.owner_user_id == user_id))
        ],
        "social": {
            "following": list(
                session.scalars(
                    select(Follow.followed_user_id).where(Follow.follower_user_id == user_id)
                )
            ),
            "likes": list(session.scalars(select(Like.work_id).where(Like.user_id == user_id))),
            "bookmarks": list(
                session.scalars(select(Bookmark.work_id).where(Bookmark.user_id == user_id))
            ),
        },
    }

    key = f"{EXPORT_PREFIX}/{user_id}/{utcnow():%Y%m%d}-{secrets.token_hex(8)}.json"
    s3.put_object(
        key,
        json.dumps(bundle, ensure_ascii=False, indent=2).encode(),
        content_type="application/json",
    )
    return key


def anonymise_user(session: Session, user_id: str, *, actor_user_id: str | None = None) -> User:
    """Erases identity while preserving the creative chain.

    Works become tombstones rather than disappearing, because a descendant that
    cannot name its ancestor is exactly the unattributed remix the platform
    promises never to produce.
    """
    user = session.get(User, user_id)
    if user is None:
        raise NotFound("用户不存在。")

    placeholder = f"deleted-{secrets.token_hex(6)}"
    user.email = f"{placeholder}@{ANONYMISED_DOMAIN}"
    user.password_hash = secrets.token_urlsafe(32)
    user.status = UserStatus.DELETED
    user.identity_provider_id = None
    user.suspended_reason = None

    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is not None:
        profile.display_name = "已注销用户"
        profile.handle = placeholder
        profile.bio = None
        profile.location = None
        profile.avatar_asset_id = None
        profile.cover_asset_id = None
        profile.public_profile = False

    for work in session.scalars(select(Work).where(Work.owner_user_id == user_id)):
        work.lifecycle_status = LifecycleStatus.TOMBSTONE
        work.visibility = Visibility.PRIVATE
        work.tombstoned_at = utcnow()
        work.tombstone_reason = "user_deleted"

    session.flush()
    logger.info("user %s anonymised by %s", user_id, actor_user_id or "system")
    return user


def signed_export_url(object_key: str, *, expires_in: int = 900) -> str:
    return s3.presign_get(object_key, expires_in=expires_in, download_name="zaolang-export.json")


def _profile_payload(profile: Profile | None) -> dict[str, object] | None:
    if profile is None:
        return None
    return {
        "display_name": profile.display_name,
        "handle": profile.handle,
        "bio": profile.bio,
        "location": profile.location,
    }


def _works_payload(session: Session, user_id: str) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for work in session.scalars(select(Work).where(Work.owner_user_id == user_id)):
        version = session.get(WorkVersion, work.current_version_id or "")
        payload.append(
            {
                "id": work.id,
                "visibility": work.visibility,
                "lifecycle_status": work.lifecycle_status,
                "title": version.title if version else None,
                "published_at": work.published_at.isoformat() if work.published_at else None,
            }
        )
    return payload


def _credits_payload(session: Session, account: CreditAccount | None) -> dict[str, object]:
    if account is None:
        return {"available": 0, "reserved": 0, "ledger": []}
    entries = session.scalars(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.account_id == account.id)
        .order_by(CreditLedgerEntry.created_at)
    )
    return {
        "available": account.available_balance,
        "reserved": account.reserved_balance,
        "ledger": [
            {
                "type": e.type,
                "amount": e.amount,
                "balance_after": e.balance_after,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
    }


def purge_expired_exports(session: Session, *, older_than_days: int = 30) -> int:
    """Export bundles are personal data; they must not linger indefinitely."""
    from app.models import DataRequest
    from app.models.enums import DataRequestStatus, DataRequestType

    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    purged = 0
    stale = session.scalars(
        select(DataRequest).where(
            DataRequest.type == DataRequestType.EXPORT,
            DataRequest.status == DataRequestStatus.COMPLETED,
            DataRequest.handled_at < cutoff,
            DataRequest.result_object_key.is_not(None),
        )
    )
    for record in stale:
        try:
            s3.delete_object(str(record.result_object_key))
        except Exception:
            logger.exception("could not delete export %s", record.result_object_key)
            continue
        record.result_object_key = None
        purged += 1
    session.flush()
    return purged
