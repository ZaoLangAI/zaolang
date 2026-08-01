"""Upload handshake, fingerprinting and AI provenance."""

from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, ValidationFailed
from app.domain.media import service as media_service
from app.models import User
from app.models.enums import ModerationStatus, Visibility
from app.storage import s3


def _png(colour: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _presign(session: Session, user: User, payload: bytes, purpose: str = "generation_reference"):  # type: ignore[no-untyped-def]
    return media_service.presign_upload(
        session,
        user_id=user.id,
        filename="frame.png",
        mime_type="image/png",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        purpose=purpose,
    )


def test_an_unsupported_type_is_refused_before_a_url_is_issued(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        media_service.presign_upload(
            db,
            user_id=author.id,
            filename="payload.svg",
            mime_type="image/svg+xml",
            size_bytes=100,
            checksum_sha256="0" * 64,
            purpose="generation_reference",
        )


def test_an_oversized_file_is_refused(db: Session, author: User) -> None:
    limit = s3.MAX_UPLOAD_BYTES["avatar"]
    with pytest.raises(ValidationFailed):
        media_service.presign_upload(
            db,
            user_id=author.id,
            filename="huge.png",
            mime_type="image/png",
            size_bytes=limit + 1,
            checksum_sha256="0" * 64,
            purpose="avatar",
        )


def test_the_object_key_is_scoped_to_the_owner_and_purpose(db: Session, author: User) -> None:
    """The directory alone proves who may write there, so a leaked signature
    cannot reach another user's space."""
    presigned = _presign(db, author, _png((10, 20, 30)))
    key = presigned.upload_session.object_key
    assert key.startswith(f"{s3.PURPOSE_PREFIXES['generation_reference']}/{author.id}/")


def test_a_completed_upload_becomes_a_private_pending_asset(db: Session, author: User) -> None:
    payload = _png((120, 40, 60))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    assert asset.visibility == Visibility.PRIVATE
    assert asset.moderation_status == ModerationStatus.PENDING
    assert asset.width == 64 and asset.height == 64


def test_bytes_that_do_not_match_the_declared_checksum_are_rejected_and_deleted(
    db: Session, author: User
) -> None:
    """The checksum was part of what the signature authorised; trusting the
    bytes instead would let a signed URL smuggle in different content."""
    promised = _png((1, 2, 3))
    substituted = _png((250, 250, 250))
    # The declared size matches so the check under test is the checksum, not
    # the length.
    presigned = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="frame.png",
        mime_type="image/png",
        size_bytes=len(substituted),
        checksum_sha256=hashlib.sha256(promised).hexdigest(),
        purpose="generation_reference",
    )
    s3.put_object(presigned.upload_session.object_key, substituted, content_type="image/png")

    with pytest.raises(ValidationFailed):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )
    assert s3.head_object(presigned.upload_session.object_key) is None


def test_a_size_mismatch_is_rejected(db: Session, author: User) -> None:
    payload = _png((5, 5, 5))
    presigned = _presign(db, author, payload)
    s3.put_object(
        presigned.upload_session.object_key,
        _png((5, 5, 5), size=(256, 256)),
        content_type="image/png",
    )

    with pytest.raises(ValidationFailed):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_completing_before_uploading_is_a_conflict_not_a_crash(db: Session, author: User) -> None:
    presigned = _presign(db, author, _png((9, 9, 9)))
    with pytest.raises(Conflict):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_another_user_cannot_complete_someone_elses_upload(
    db: Session, author: User, remixer: User
) -> None:
    payload = _png((44, 55, 66))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    with pytest.raises(Forbidden):
        media_service.complete_upload(
            db, user_id=remixer.id, upload_session_id=presigned.upload_session.id
        )


def test_completing_twice_returns_the_same_asset(db: Session, author: User) -> None:
    payload = _png((77, 88, 99))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    first = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    second = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    assert first.id == second.id


def test_an_expired_session_cannot_be_completed(db: Session, author: User) -> None:
    import datetime as dt

    from app.models.base import utcnow

    payload = _png((3, 3, 3))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    presigned.upload_session.expires_at = utcnow() - dt.timedelta(seconds=1)
    db.flush()

    with pytest.raises(Conflict):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_identical_images_produce_identical_fingerprints(db: Session, author: User) -> None:
    payload = _png((30, 60, 90))
    first = _presign(db, author, payload)
    s3.put_object(first.upload_session.object_key, payload, content_type="image/png")
    asset_a = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=first.upload_session.id
    )

    second = _presign(db, author, payload)
    s3.put_object(second.upload_session.object_key, payload, content_type="image/png")
    asset_b = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=second.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    hashes = {
        row.asset_id: row.fingerprint_hex
        for row in db.scalars(
            select(ContentFingerprint).where(
                ContentFingerprint.asset_id.in_([asset_a.id, asset_b.id])
            )
        )
    }
    assert hashes[asset_a.id] == hashes[asset_b.id]


def test_a_reupload_is_found_as_a_near_duplicate(db: Session, author: User) -> None:
    payload = _png((200, 100, 50))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    original = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    fingerprint = db.scalar(
        select(ContentFingerprint).where(ContentFingerprint.asset_id == original.id)
    )
    assert fingerprint is not None

    matches = media_service.find_near_duplicates(
        db, fingerprint_hex=fingerprint.fingerprint_hex, exclude_asset_id=None
    )
    assert original.id in {asset.id for asset, _ in matches}


def test_a_fingerprint_fits_the_signed_bigint_range(db: Session, author: User) -> None:
    """A pHash is an unsigned 64-bit value; storing it raw would overflow the
    Postgres column."""
    payload = _png((255, 255, 255))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    fingerprint = db.scalar(
        select(ContentFingerprint).where(ContentFingerprint.asset_id == asset.id)
    )
    assert fingerprint is not None
    assert -(2**63) <= fingerprint.fingerprint_bits < 2**63


def test_generated_output_carries_an_ai_disclosure_claim(db: Session, author: User) -> None:
    payload = _png((11, 22, 33))
    key = f"outputs/{author.id}/generated.png"
    s3.put_object(key, payload, content_type="image/png")

    asset = media_service.register_generated_asset(
        db,
        owner_user_id=author.id,
        object_key=key,
        mime_type="image/png",
        width=64,
        height=64,
        duration_ms=None,
        generation_job_id="job_test",
    )

    manifest = media_service.provenance_for(db, asset.id)
    assert manifest is not None
    assert manifest.generation_job_id == "job_test"
    labels = {a["label"] for a in manifest.claim_json["assertions"]}
    assert "c2pa.actions" in labels
    # No signer is configured, and an unsigned claim must say so rather than
    # look verified.
    assert manifest.signature is None


def test_a_private_asset_is_invisible_to_a_stranger(
    db: Session, author: User, remixer: User
) -> None:
    payload = _png((70, 70, 70))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        media_service.signed_url_for(db, asset_id=asset.id, viewer_user_id=remixer.id)

    url = media_service.signed_url_for(db, asset_id=asset.id, viewer_user_id=author.id)
    assert "X-Amz-Signature" in url
