"""Voice-clone samples and real-person references need that person's consent.

`consent.assert_reference_consents` runs inside `jobs.service.submit` after the
ownership check and before quoting, so a missing consent is refused without
reserving any credits (深度合成管理规定 §14).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.compliance import service as compliance
from app.domain.consent import service as consent_service
from app.domain.errors import AssetRightsRequired, NotFound, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.media import service as media_service
from app.models import Asset, AssetConsent, CreditAccount, GenerationJob, User
from app.models.base import new_id, utcnow
from app.models.enums import (
    AssetRole,
    ConsentStatus,
    MediaType,
    ModerationStatus,
    Operation,
    QualityTier,
    Visibility,
)
from app.models.platform import AuditLog
from app.storage import s3
from tests.conftest import auth_header

_MIME = {MediaType.AUDIO: "audio/mpeg", MediaType.IMAGE: "image/png", MediaType.VIDEO: "video/mp4"}


def _asset(
    session: Session,
    owner: User,
    media_type: MediaType,
    *,
    real_person: bool = False,
    role: AssetRole = AssetRole.GENERATION_REFERENCE,
) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}",
        media_type=media_type,
        mime_type=_MIME[media_type],
        size_bytes=128,
        checksum_sha256="a" * 64,
        role=role,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
        depicts_real_person=real_person,
    )
    session.add(asset)
    session.flush()
    return asset


def _declare(session: Session, owner: User, asset: Asset, consent_type: str) -> AssetConsent:
    return consent_service.declare(
        session,
        user=owner,
        asset_id=asset.id,
        consent_type=consent_type,
        subject_reference="配音演员 A",
    )


def test_voice_clone_submit_is_refused_before_anything_is_reserved(
    db: Session, author: User
) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    with pytest.raises(AssetRightsRequired) as refused:
        jobs_service.submit(
            db,
            user_id=author.id,
            operation=Operation.AUDIO_GENERATION.value,
            quality_tier=QualityTier.STANDARD.value,
            params={"prompt": "念一句台词", "reference_asset_ids": [sample.id]},
            idempotency_key=new_id("idem"),
        )
    assert refused.value.details == {"asset_id": sample.id, "consent_type": "voice"}
    assert db.scalar(select(GenerationJob).where(GenerationJob.user_id == author.id)) is None
    account = db.scalar(select(CreditAccount).where(CreditAccount.user_id == author.id))
    assert account is None or account.reserved_balance == 0


def test_a_declared_voice_consent_lets_the_sample_through(db: Session, author: User) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    consent = _declare(db, author, sample, "voice")

    assert consent.status == ConsentStatus.DECLARED
    assert consent.declared_by_user_id == author.id
    consent_service.assert_reference_consents(
        db, operation=Operation.AUDIO_GENERATION.value, params={"reference_asset_ids": [sample.id]}
    )

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "consent.declare", AuditLog.target_id == consent.id
        )
    )
    assert entry is not None
    # The subject's name stays on the consent row, out of the operator-readable log.
    assert "配音演员 A" not in str(entry.after_json)


def test_revoked_or_expired_consent_blocks_the_sample_again(db: Session, author: User) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    params = {"reference_asset_ids": [sample.id]}
    operation = Operation.AUDIO_GENERATION.value

    consent = _declare(db, author, sample, "voice")
    revoked = consent_service.revoke(db, user=author, consent_id=consent.id, reason="撤回授权")
    assert revoked.status == ConsentStatus.REVOKED
    assert revoked.revoked_at is not None
    assert consent_service.revoke(db, user=author, consent_id=consent.id) is revoked  # idempotent
    with pytest.raises(AssetRightsRequired):
        consent_service.assert_reference_consents(db, operation=operation, params=params)

    expiring = _declare(db, author, sample, "voice")
    expiring.expires_at = utcnow() - dt.timedelta(minutes=1)
    db.flush()
    with pytest.raises(AssetRightsRequired):
        consent_service.assert_reference_consents(db, operation=operation, params=params)


def test_real_person_references_need_a_portrait_consent(db: Session, author: User) -> None:
    photo = _asset(db, author, MediaType.IMAGE, real_person=True)
    plain = _asset(db, author, MediaType.IMAGE)

    consent_service.assert_reference_consents(
        db, operation=Operation.IMAGE_TO_VIDEO.value, params={"reference_asset_ids": [plain.id]}
    )
    with pytest.raises(AssetRightsRequired) as as_reference:
        consent_service.assert_reference_consents(
            db, operation=Operation.IMAGE_TO_IMAGE.value, params={"reference_asset_ids": [photo.id]}
        )
    assert as_reference.value.details["consent_type"] == "portrait"
    with pytest.raises(AssetRightsRequired):
        consent_service.assert_reference_consents(
            db,
            operation=Operation.IMAGE_TO_VIDEO.value,
            params={"video_options": {"first_frame_asset_id": photo.id}},
        )

    _declare(db, author, photo, "portrait")
    consent_service.assert_reference_consents(
        db,
        operation=Operation.IMAGE_TO_VIDEO.value,
        params={"video_options": {"first_frame_asset_id": photo.id}},
    )


def test_declare_checks_media_type_ownership_subject_and_evidence(
    db: Session, author: User, remixer: User
) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    photo = _asset(db, author, MediaType.IMAGE)

    with pytest.raises(ValidationFailed, match="声音授权"):
        _declare(db, author, photo, "voice")
    with pytest.raises(ValidationFailed, match="肖像授权"):
        _declare(db, author, sample, "portrait")
    with pytest.raises(NotFound):
        _declare(db, remixer, sample, "voice")
    with pytest.raises(ValidationFailed, match="姓名"):
        consent_service.declare(
            db, user=author, asset_id=sample.id, consent_type="voice", subject_reference="   "
        )

    not_evidence = _asset(db, author, MediaType.IMAGE)
    with pytest.raises(ValidationFailed, match="授权凭证"):
        consent_service.declare(
            db,
            user=author,
            asset_id=sample.id,
            consent_type="voice",
            subject_reference="本人",
            evidence_asset_id=not_evidence.id,
        )
    evidence = _asset(db, author, MediaType.IMAGE, role=AssetRole.CONSENT_EVIDENCE)
    consent = consent_service.declare(
        db,
        user=author,
        asset_id=sample.id,
        consent_type="voice",
        subject_reference="本人",
        evidence_asset_id=evidence.id,
    )
    assert consent.evidence_asset_id == evidence.id


def test_account_deletion_revokes_the_users_consents(db: Session, author: User) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    consent = _declare(db, author, sample, "voice")

    compliance.anonymise_user(db, author.id)

    db.refresh(consent)
    assert consent.status == ConsentStatus.REVOKED
    assert consent.revoked_at is not None
    with pytest.raises(AssetRightsRequired):
        consent_service.assert_reference_consents(
            db,
            operation=Operation.AUDIO_GENERATION.value,
            params={"reference_asset_ids": [sample.id]},
        )


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_real_person_flag_travels_from_presign_to_the_asset(db: Session, author: User) -> None:
    payload = _png()
    presigned = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="face.png",
        mime_type="image/png",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        purpose="generation_reference",
        depicts_real_person=True,
    )
    assert presigned.upload_session.depicts_real_person is True
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    assert asset.depicts_real_person is True

    # Audio cannot "show" a person — the flag is dropped rather than stored.
    audio = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="voice.mp3",
        mime_type="audio/mpeg",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        purpose="voice_sample",
        depicts_real_person=True,
    )
    assert audio.upload_session.depicts_real_person is False


def test_consent_routes_declare_list_and_revoke(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    sample = _asset(db, author, MediaType.AUDIO)
    headers = auth_header(author)

    created = client.post(
        f"/v1/assets/{sample.id}/consents",
        json={"consent_type": "voice", "subject_reference": "本人"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "declared"
    assert body["has_evidence"] is False

    listed = client.get(f"/v1/assets/{sample.id}/consents", headers=headers)
    assert [item["id"] for item in listed.json()] == [body["id"]]

    foreign = client.get(f"/v1/assets/{sample.id}/consents", headers=auth_header(remixer))
    assert foreign.status_code == 404

    revoked = client.post(
        f"/v1/asset-consents/{body['id']}/revoke", json={"reason": "不再授权"}, headers=headers
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
