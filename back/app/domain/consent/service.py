"""Consent for real people's voices and likenesses used as generation input.

Cloning someone's voice or editing their face needs that person's separate
consent (《互联网信息服务深度合成管理规定》第十四条). An uploaded voice-clone
sample — or a reference image/video its uploader flagged as depicting a real
person (`Asset.depicts_real_person`) — may only feed a generation job while an
active `AssetConsent` of the matching type covers it. `jobs.service.submit`
calls `assert_reference_consents` before anything is quoted or reserved, so a
missing consent never costs the user credits.

Deliberate limits (documented in zaolang-compliance-audit):
- an idempotent replay of an already-created job returns before this check,
  so revoking a consent does not retroactively block that one job;
- the worker does not re-check at run time;
- a frame cut from a real-person video inherits the flag, not the consent —
  it needs its own declaration, so revoking one consent can never leave a
  copied one behind.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.audit import service as audit
from app.domain.errors import AssetRightsRequired, NotFound, ValidationFailed
from app.models import Asset, AssetConsent, User
from app.models.base import utcnow
from app.models.enums import AssetRole, ConsentStatus, ConsentType, MediaType, Operation

ACTIVE_STATUSES = (ConsentStatus.DECLARED.value, ConsentStatus.VERIFIED.value)
SUPPORTED_TYPES = frozenset({ConsentType.VOICE.value, ConsentType.PORTRAIT.value})
SUBJECT_MAX_LENGTH = 255

_MISSING_MESSAGE = {
    ConsentType.VOICE.value: "使用声音克隆前，请先提交被克隆人的授权声明。",
    ConsentType.PORTRAIT.value: "该参考素材含真人肖像，请先提交肖像授权声明。",
}


def required_consent_type(operation: str, asset: Asset) -> str | None:
    """Which consent, if any, `asset` needs before it may feed `operation`.

    Every audio reference an `audio_generation` job takes is a voice-clone
    sample (the operation accepts no other kind), so any audio reference
    there means cloning somebody's voice.
    """
    if operation == Operation.AUDIO_GENERATION.value and asset.media_type == MediaType.AUDIO:
        return ConsentType.VOICE.value
    if asset.depicts_real_person and asset.media_type in (MediaType.IMAGE, MediaType.VIDEO):
        return ConsentType.PORTRAIT.value
    return None


def active_consent(session: Session, *, asset_id: str, consent_type: str) -> AssetConsent | None:
    now = utcnow()
    return session.scalar(
        select(AssetConsent)
        .where(
            AssetConsent.asset_id == asset_id,
            AssetConsent.consent_type == consent_type,
            AssetConsent.status.in_(ACTIVE_STATUSES),
            AssetConsent.revoked_at.is_(None),
            or_(AssetConsent.expires_at.is_(None), AssetConsent.expires_at > now),
        )
        .order_by(AssetConsent.created_at.desc())
        .limit(1)
    )


def _reference_ids(params: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in params.get("reference_asset_ids") or [] if item]
    video_options = params.get("video_options") or {}
    if isinstance(video_options, Mapping):
        for key in ("first_frame_asset_id", "last_frame_asset_id"):
            value = video_options.get(key)
            if value:
                ids.append(str(value))
    return ids


def assert_reference_consents(
    session: Session, *, operation: str, params: Mapping[str, Any]
) -> None:
    """Raises `AssetRightsRequired` when a voice sample or a real-person
    reference in this request has no active consent.

    Call after `media.validate_generation_references` (ownership is already
    proven there) and before quoting. Character/scene references merged in by
    `apply_character_refs`/`apply_scene_refs` are covered too, since they end
    up in `reference_asset_ids` first.
    """
    ids = _reference_ids(params)
    if not ids:
        return
    for asset in session.scalars(select(Asset).where(Asset.id.in_(ids))):
        needed = required_consent_type(operation, asset)
        if needed is None or active_consent(session, asset_id=asset.id, consent_type=needed):
            continue
        raise AssetRightsRequired(_MISSING_MESSAGE[needed], asset_id=asset.id, consent_type=needed)


def _owned_asset(session: Session, *, user_id: str, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != user_id:
        # 404, not 403 — same anti-probing stance as `GET /assets/{id}`.
        raise NotFound("素材不存在。")
    return asset


def declare(
    session: Session,
    *,
    user: User,
    asset_id: str,
    consent_type: str,
    subject_reference: str,
    evidence_asset_id: str | None = None,
    expires_at: dt.datetime | None = None,
    request: Request | None = None,
) -> AssetConsent:
    """Records the uploader's declaration that the person in `asset` consented.

    Starts as `declared`; an operator may later mark it `verified` against the
    evidence. The subject's name stays on the consent row only — it is not
    copied into the audit log, which operators browse.
    """
    asset = _owned_asset(session, user_id=user.id, asset_id=asset_id)
    if consent_type not in SUPPORTED_TYPES:
        raise ValidationFailed(
            "不支持的授权类型。", fields={"consent_type": "只能是 voice 或 portrait"}
        )
    if consent_type == ConsentType.VOICE.value and asset.media_type != MediaType.AUDIO:
        raise ValidationFailed("声音授权只能关联音频素材。", fields={"asset_id": "必须是音频"})
    if consent_type == ConsentType.PORTRAIT.value and asset.media_type not in (
        MediaType.IMAGE,
        MediaType.VIDEO,
    ):
        raise ValidationFailed(
            "肖像授权只能关联图片或视频素材。", fields={"asset_id": "必须是图片或视频"}
        )
    subject = subject_reference.strip()
    if not subject or len(subject) > SUBJECT_MAX_LENGTH:
        raise ValidationFailed(
            "请填写被授权人的姓名或称呼。",
            fields={"subject_reference": f"必填，最多 {SUBJECT_MAX_LENGTH} 字"},
        )
    if evidence_asset_id is not None:
        evidence = session.get(Asset, evidence_asset_id)
        if (
            evidence is None
            or evidence.owner_user_id != user.id
            or evidence.role != AssetRole.CONSENT_EVIDENCE
        ):
            raise ValidationFailed(
                "授权凭证不存在或不属于当前用户。", fields={"evidence_asset_id": "不可用"}
            )
    if expires_at is not None and expires_at <= utcnow():
        raise ValidationFailed("授权有效期必须晚于当前时间。", fields={"expires_at": "已过期"})

    consent = AssetConsent(
        asset_id=asset.id,
        consent_type=consent_type,
        subject_reference=subject,
        evidence_asset_id=evidence_asset_id,
        status=ConsentStatus.DECLARED.value,
        expires_at=expires_at,
        declared_by_user_id=user.id,
    )
    session.add(consent)
    session.flush()
    audit.record(
        session,
        actor=user,
        action="consent.declare",
        target_type="asset_consent",
        target_id=consent.id,
        after={
            "asset_id": asset.id,
            "consent_type": consent_type,
            "status": consent.status,
            "has_evidence": evidence_asset_id is not None,
        },
        request=request,
    )
    return consent


def revoke(
    session: Session,
    *,
    user: User,
    consent_id: str,
    reason: str | None = None,
    request: Request | None = None,
) -> AssetConsent:
    """Withdraws a consent. Idempotent: revoking twice changes nothing."""
    consent = session.get(AssetConsent, consent_id)
    if consent is None:
        raise NotFound("授权记录不存在。")
    _owned_asset(session, user_id=user.id, asset_id=consent.asset_id)
    if consent.status == ConsentStatus.REVOKED.value:
        return consent
    before = {"status": consent.status}
    consent.status = ConsentStatus.REVOKED.value
    consent.revoked_at = utcnow()
    session.flush()
    audit.record(
        session,
        actor=user,
        action="consent.revoke",
        target_type="asset_consent",
        target_id=consent.id,
        before=before,
        after={"status": consent.status},
        reason=reason,
        request=request,
    )
    return consent


def list_for_asset(session: Session, *, user_id: str, asset_id: str) -> list[AssetConsent]:
    _owned_asset(session, user_id=user_id, asset_id=asset_id)
    return list(
        session.scalars(
            select(AssetConsent)
            .where(AssetConsent.asset_id == asset_id)
            .order_by(AssetConsent.created_at.desc())
        )
    )


def revoke_all_for_user(session: Session, *, user_id: str) -> int:
    """Account deletion: nothing the user declared, and nothing covering their
    own assets, stays active. Returns how many consents were revoked."""
    owned_assets = select(Asset.id).where(Asset.owner_user_id == user_id)
    consents = list(
        session.scalars(
            select(AssetConsent).where(
                AssetConsent.status.in_(ACTIVE_STATUSES),
                or_(
                    AssetConsent.declared_by_user_id == user_id,
                    AssetConsent.asset_id.in_(owned_assets),
                ),
            )
        )
    )
    now = utcnow()
    for consent in consents:
        consent.status = ConsentStatus.REVOKED.value
        consent.revoked_at = now
    session.flush()
    return len(consents)
