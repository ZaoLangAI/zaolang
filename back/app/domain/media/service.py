"""Upload lifecycle and content integrity.

An upload is a two-step handshake. `presign` records exactly what the client
promised — user, key, MIME type, size, checksum, purpose — and `complete`
verifies the stored object against that promise before an `Asset` exists. A
signed URL therefore cannot be replayed to smuggle in a different file, a
different type, or a file belonging to a different purpose.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import imagehash
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import Asset, ContentFingerprint, ProvenanceManifest, UploadSession
from app.models.base import new_id, utcnow
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from app.storage import s3

logger = logging.getLogger(__name__)

PURPOSE_TO_ROLE: dict[str, AssetRole] = {
    "generation_reference": AssetRole.GENERATION_REFERENCE,
    "avatar": AssetRole.AVATAR,
    "profile_cover": AssetRole.PROFILE_COVER,
    "consent_evidence": AssetRole.CONSENT_EVIDENCE,
}

# Two images within this Hamming distance are treated as the same content.
DUPLICATE_HAMMING_THRESHOLD = 6


@dataclass(slots=True)
class PresignedUpload:
    upload_session: UploadSession
    upload_url: str
    required_headers: dict[str, str]


def presign_upload(
    session: Session,
    *,
    user_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    checksum_sha256: str,
    purpose: str,
) -> PresignedUpload:
    settings = get_settings()

    extension = s3.ALLOWED_UPLOAD_MIME_TYPES.get(mime_type)
    if extension is None:
        raise ValidationFailed(f"不支持的文件类型: {mime_type}", mime_type=mime_type)
    if purpose not in s3.PURPOSE_PREFIXES:
        raise ValidationFailed(f"不支持的用途: {purpose}", purpose=purpose)

    limit = s3.MAX_UPLOAD_BYTES[purpose]
    if size_bytes > limit:
        raise ValidationFailed(
            f"文件超过 {limit // (1024 * 1024)}MB 上限。", size_bytes=size_bytes, limit=limit
        )
    if purpose in ("avatar", "profile_cover") and not mime_type.startswith("image/"):
        raise ValidationFailed("头像与封面必须是图片。", mime_type=mime_type)

    # The key embeds the owner, so an object's directory alone proves who may
    # write to it.
    object_key = f"{s3.PURPOSE_PREFIXES[purpose]}/{user_id}/{new_id('obj')}{extension}"
    expires_at = utcnow() + dt.timedelta(seconds=settings.upload_url_ttl_seconds)

    upload_session = UploadSession(
        user_id=user_id,
        object_key=object_key,
        purpose=purpose,
        mime_type=mime_type,
        declared_size_bytes=size_bytes,
        declared_checksum_sha256=checksum_sha256,
        expires_at=expires_at,
    )
    session.add(upload_session)
    session.flush()

    url = s3.presign_put(
        object_key, content_type=mime_type, expires_in=settings.upload_url_ttl_seconds
    )
    return PresignedUpload(
        upload_session=upload_session,
        upload_url=url,
        required_headers={"Content-Type": mime_type},
    )


def complete_upload(session: Session, *, user_id: str, upload_session_id: str) -> Asset:
    """Verifies the stored object and creates the asset."""
    upload = session.get(UploadSession, upload_session_id)
    if upload is None:
        raise NotFound("上传会话不存在。")
    if upload.user_id != user_id:
        raise Forbidden("不能完成他人的上传。")
    if upload.completed_at is not None:
        existing = session.get(Asset, upload.asset_id) if upload.asset_id else None
        if existing is not None:
            return existing
        raise Conflict("上传会话已结束。")
    if upload.expires_at < utcnow():
        raise Conflict("上传链接已过期，请重新发起。")

    head = s3.head_object(upload.object_key)
    if head is None:
        raise Conflict("尚未检测到已上传的文件。")
    if head["size_bytes"] != upload.declared_size_bytes:
        raise ValidationFailed(
            "文件大小与申请时不一致。",
            declared=upload.declared_size_bytes,
            actual=head["size_bytes"],
        )

    payload = s3.get_object(upload.object_key)
    actual_checksum = hashlib.sha256(payload).hexdigest()
    if actual_checksum != upload.declared_checksum_sha256:
        # Refuse rather than trust the bytes: the promise was part of what the
        # signature authorised.
        s3.delete_object(upload.object_key)
        raise ValidationFailed("文件校验和与申请时不一致。")

    width, height, media_type = _probe(payload, upload.mime_type)

    asset = Asset(
        owner_user_id=user_id,
        object_key=upload.object_key,
        media_type=media_type,
        mime_type=upload.mime_type,
        size_bytes=head["size_bytes"],
        checksum_sha256=actual_checksum,
        role=PURPOSE_TO_ROLE[upload.purpose],
        width=width,
        height=height,
        moderation_status=ModerationStatus.PENDING,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()

    upload.completed_at = utcnow()
    upload.asset_id = asset.id
    session.flush()

    if media_type == MediaType.IMAGE:
        record_fingerprint(session, asset=asset, payload=payload)
    return asset


def object_keys_for(session: Session, *, asset_ids: Sequence[str]) -> list[str]:
    """Resolves reference asset ids to storage keys for a provider request.

    Order is preserved and missing ids are skipped rather than raising: by the
    time the pipeline runs, ownership was already checked at submission, so a
    gap here means the asset was deleted, not a request to reject.
    """
    if not asset_ids:
        return []
    rows = session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
    by_id = {asset.id: asset.object_key for asset in rows}
    return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]


def register_generated_asset(
    session: Session,
    *,
    owner_user_id: str,
    object_key: str,
    mime_type: str,
    width: int | None,
    height: int | None,
    duration_ms: int | None,
    is_prototype: bool = True,
    generation_job_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> Asset:
    """Registers provider output, which bypasses the upload handshake because
    the platform itself produced the bytes."""
    payload = s3.get_object(object_key)
    asset = Asset(
        owner_user_id=owner_user_id,
        object_key=object_key,
        media_type=_media_type_for(mime_type),
        mime_type=mime_type,
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=AssetRole.GENERATION_OUTPUT,
        width=width,
        height=height,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.PENDING,
        visibility=Visibility.PRIVATE,
        is_prototype=is_prototype,
    )
    session.add(asset)
    session.flush()

    if asset.media_type == MediaType.IMAGE:
        record_fingerprint(session, asset=asset, payload=payload)
    record_provenance(
        session,
        asset=asset,
        generation_job_id=generation_job_id,
        details=provenance or {},
    )
    return asset


def record_provenance(
    session: Session,
    *,
    asset: Asset,
    generation_job_id: str | None,
    details: dict[str, Any],
) -> ProvenanceManifest:
    """Attaches the AI disclosure claim to a generated asset.

    The claim follows the shape of a C2PA assertion set so that turning on a
    real signer later is a matter of filling in `signature`, not reshaping the
    stored data.
    """
    claim = {
        "claim_generator": "zaolang",
        "format": asset.mime_type,
        "instance_id": asset.id,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": (
                                "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
                            ),
                            "when": utcnow().isoformat(),
                        }
                    ]
                },
            },
            {
                "label": "c2pa.hash.data",
                "data": {"alg": "sha256", "hash": asset.checksum_sha256},
            },
        ],
        **details,
    }

    manifest = ProvenanceManifest(
        asset_id=asset.id,
        generation_job_id=generation_job_id,
        claim_json=claim,
        # Stays null until a signing identity is configured; an unsigned claim
        # is honest about being unverifiable.
        signature=None,
    )
    session.add(manifest)
    session.flush()
    return manifest


def provenance_for(session: Session, asset_id: str) -> ProvenanceManifest | None:
    return session.scalar(select(ProvenanceManifest).where(ProvenanceManifest.asset_id == asset_id))


def record_fingerprint(
    session: Session, *, asset: Asset, payload: bytes
) -> ContentFingerprint | None:
    """Stores a perceptual hash for duplicate and laundering detection."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            phash = imagehash.phash(image.convert("RGB"))
    except (UnidentifiedImageError, OSError):
        logger.warning("could not fingerprint asset %s", asset.id)
        return None

    hex_value = str(phash)
    fingerprint = ContentFingerprint(
        asset_id=asset.id,
        algorithm="phash",
        fingerprint_hex=hex_value,
        fingerprint_bits=_to_signed_64(int(hex_value, 16)),
        frame_index=0,
    )
    session.add(fingerprint)
    session.flush()
    return fingerprint


def _to_signed_64(value: int) -> int:
    """Maps a 64-bit hash onto Postgres' signed bigint range."""
    masked = value & 0xFFFF_FFFF_FFFF_FFFF
    return masked - (1 << 64) if masked >= (1 << 63) else masked


def hamming_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def find_near_duplicates(
    session: Session, *, fingerprint_hex: str, exclude_asset_id: str | None = None, limit: int = 20
) -> list[tuple[Asset, int]]:
    """Finds visually similar assets.

    Compared in Python rather than SQL: pHash similarity is a bit-distance, not
    an ordering, so an index cannot answer it directly. The candidate set stays
    small because it is only ever run from the ops console.
    """
    rows = session.scalars(
        select(ContentFingerprint).where(ContentFingerprint.algorithm == "phash")
    )
    matches: list[tuple[Asset, int]] = []
    for row in rows:
        if exclude_asset_id and row.asset_id == exclude_asset_id:
            continue
        distance = hamming_distance(fingerprint_hex, row.fingerprint_hex)
        if distance <= DUPLICATE_HAMMING_THRESHOLD:
            asset = session.get(Asset, row.asset_id)
            if asset is not None:
                matches.append((asset, distance))
    matches.sort(key=lambda pair: pair[1])
    return matches[:limit]


def signed_url_for(
    session: Session, *, asset_id: str, viewer_user_id: str | None, viewer_is_staff: bool = False
) -> str:
    """Mints a short-lived URL after an access check.

    Generation output and consent evidence stay owner-only until the work that
    contains them is published.
    """
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在。")

    is_owner = asset.owner_user_id == viewer_user_id
    if not (is_owner or viewer_is_staff or asset.visibility != Visibility.PRIVATE):
        raise NotFound("素材不存在。")

    settings = get_settings()
    return s3.presign_get(asset.object_key, expires_in=settings.download_url_ttl_seconds)


def publish_asset(session: Session, asset: Asset) -> None:
    """Makes an asset readable by anyone who can see its work."""
    asset.visibility = Visibility.PUBLIC_VIEW_ONLY
    session.flush()


def _probe(payload: bytes, mime_type: str) -> tuple[int | None, int | None, MediaType]:
    media_type = _media_type_for(mime_type)
    if media_type != MediaType.IMAGE:
        return None, None, media_type
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height, MediaType.IMAGE
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationFailed("无法解析该图片文件。") from exc


def _media_type_for(mime_type: str) -> MediaType:
    if mime_type.startswith("video/"):
        return MediaType.VIDEO
    if mime_type.startswith("audio/"):
        return MediaType.AUDIO
    return MediaType.IMAGE
