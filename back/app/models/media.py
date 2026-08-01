"""Assets, upload sessions, consents and perceptual fingerprints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import ConsentStatus, ModerationStatus, Visibility


class Asset(Base, TimestampMixin):
    """A stored object. Private assets are only ever served through a
    short-lived signed URL minted after an ownership check."""

    __tablename__ = "assets"

    id: Mapped[str] = id_column("ast")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moderation_status: Mapped[str] = mapped_column(
        String(24), default=ModerationStatus.PENDING, nullable=False
    )
    visibility: Mapped[str] = mapped_column(String(24), default=Visibility.PRIVATE, nullable=False)
    # Set when the seed importer created this from assets-pack; surfaced in the
    # UI so prototype media is never mistaken for user content.
    is_prototype: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (
        Index("ix_assets_owner_user_id_role", "owner_user_id", "role"),
        Index("ix_assets_checksum_sha256", "checksum_sha256"),
    )


class UploadSession(Base, TimestampMixin):
    """Binds a presigned URL to one user, key, MIME type, size and purpose.

    Completion re-checks the object against these values, so a signed upload can
    never be replayed for a different user, directory, type or purpose.
    """

    __tablename__ = "upload_sessions"

    id: Mapped[str] = id_column("upl")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_upload_sessions_user_id", "user_id"),)


class AssetConsent(Base, TimestampMixin):
    __tablename__ = "asset_consents"

    id: Mapped[str] = id_column("cns")
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default=ConsentStatus.DECLARED, nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_asset_consents_asset_id", "asset_id"),)


class ContentFingerprint(Base, TimestampMixin):
    """Perceptual hash used to spot re-uploads and near-duplicate laundering.

    Stored as a hex string plus a 64-bit integer so exact matches use the index
    and near matches use Hamming distance in the ops console.
    """

    __tablename__ = "content_fingerprints"

    id: Mapped[str] = id_column("fpr")
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    algorithm: Mapped[str] = mapped_column(String(24), default="phash", nullable=False)
    fingerprint_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_bits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "algorithm", "frame_index", name="uq_fingerprint_asset_frame"),
        Index("ix_content_fingerprints_fingerprint_bits", "fingerprint_bits"),
    )


class ProvenanceManifest(Base, TimestampMixin):
    """AI disclosure record attached to a generated output.

    Holds the claim payload we would sign with C2PA. Signing itself is not
    implemented; `signature` stays null until a real signer is configured.
    """

    __tablename__ = "provenance_manifests"

    id: Mapped[str] = id_column("prv")
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    generation_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    claim_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
