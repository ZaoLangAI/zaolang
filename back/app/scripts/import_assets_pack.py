"""Imports real media from `assets-pack/` and retires the prototype placeholders.

The repository ships with clearly-marked placeholder media so the pipeline can
be exercised end to end. When real assets arrive they land here instead of being
pasted over the placeholders by hand: the manifest says which prototype each
real file replaces, and every work version pointing at that prototype follows
along without a data migration.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.db import session_scope
from app.domain.media import service as media_service
from app.models import Asset, AssetConsent, User
from app.models.enums import (
    AssetRole,
    ConsentStatus,
    MediaType,
    ModerationStatus,
    UserRole,
    Visibility,
)
from app.storage import s3

logger = logging.getLogger("assets_pack")

SUPPORTED_MANIFEST_VERSION = 1

VALID_ROLES = {
    AssetRole.GENERATION_OUTPUT,
    AssetRole.GENERATION_REFERENCE,
    AssetRole.AVATAR,
    AssetRole.PROFILE_COVER,
}

# Roles whose subject may be a real person. Anything here without a consent
# block is refused rather than imported and flagged later.
CONSENT_REQUIRED_ROLES = {AssetRole.GENERATION_REFERENCE}


class ManifestError(Exception):
    """The manifest is unusable. Nothing is imported."""


@dataclass(slots=True)
class ImportReport:
    imported: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [
            f"新增 {len(self.imported)} 项",
            f"替换占位 {len(self.replaced)} 项",
            f"跳过 {len(self.skipped)} 项",
        ]
        if self.errors:
            lines.append("错误:")
            lines.extend(f"  - {message}" for message in self.errors)
        return "\n".join(lines)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ManifestError(f"找不到清单文件: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"清单不是合法 JSON: {exc}") from exc

    version = manifest.get("version")
    if version != SUPPORTED_MANIFEST_VERSION:
        raise ManifestError(
            f"清单版本 {version!r} 不受支持，当前支持 {SUPPORTED_MANIFEST_VERSION}。"
        )
    if not isinstance(manifest.get("items"), list):
        raise ManifestError("清单缺少 items 数组。")

    slugs = [item.get("slug") for item in manifest["items"]]
    duplicates = {slug for slug in slugs if slug and slugs.count(slug) > 1}
    if duplicates:
        raise ManifestError(f"清单内 slug 重复: {', '.join(sorted(duplicates))}")
    return manifest


def resolve_file(root: Path, relative: str) -> Path:
    """Keeps a manifest from reaching outside its own directory."""
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ManifestError(f"文件路径越出素材包目录: {relative}")
    if not candidate.is_file():
        raise ManifestError(f"文件不存在: {relative}")
    return candidate


def run(
    session: Session, *, manifest_path: Path, owner_email: str | None = None, dry_run: bool = False
) -> ImportReport:
    manifest = load_manifest(manifest_path)
    root = manifest_path.parent
    defaults = manifest.get("defaults") or {}
    owner = _resolve_owner(session, owner_email)
    report = ImportReport()

    for item in manifest["items"]:
        slug = item.get("slug")
        try:
            _import_item(
                session,
                root=root,
                item=item,
                defaults=defaults,
                owner=owner,
                pack_id=manifest.get("pack_id", manifest_path.stem),
                dry_run=dry_run,
                report=report,
            )
        except ManifestError as exc:
            report.errors.append(f"{slug}: {exc}")
        except Exception as exc:
            logger.exception("导入 %s 失败", slug)
            report.errors.append(f"{slug}: {type(exc).__name__}: {exc}")

    return report


def _import_item(
    session: Session,
    *,
    root: Path,
    item: dict[str, Any],
    defaults: dict[str, Any],
    owner: User,
    pack_id: str,
    dry_run: bool,
    report: ImportReport,
) -> None:
    slug = item.get("slug")
    if not slug:
        raise ManifestError("条目缺少 slug。")

    role = item.get("role", AssetRole.GENERATION_OUTPUT)
    if role not in VALID_ROLES:
        raise ManifestError(f"不支持的 role: {role}")

    mime_type = item.get("mime_type")
    if mime_type not in s3.ALLOWED_UPLOAD_MIME_TYPES:
        raise ManifestError(f"不支持的 mime_type: {mime_type}")

    consent = item.get("consent")
    if role in CONSENT_REQUIRED_ROLES and consent is None and item.get("depicts_real_person", True):
        raise ManifestError("参考素材可能含真人肖像，必须提供 consent 授权信息。")

    source = resolve_file(root, item["file"])
    payload = source.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()

    existing = session.scalar(
        sa.select(Asset).where(Asset.checksum_sha256 == checksum, Asset.is_prototype.is_(False))
    )
    if existing is not None:
        report.skipped.append(f"{slug} (已导入)")
        return

    width, height = item.get("width"), item.get("height")
    if mime_type.startswith("image/") and (width is None or height is None):
        width, height = _probe_dimensions(payload)

    object_key = f"packs/{pack_id}/{slug}{s3.ALLOWED_UPLOAD_MIME_TYPES[mime_type]}"

    if dry_run:
        report.imported.append(f"{slug} -> {object_key} (dry-run)")
        return

    s3.put_object(object_key, payload, content_type=mime_type)

    asset = Asset(
        owner_user_id=owner.id,
        object_key=object_key,
        media_type=_media_type_for(mime_type),
        mime_type=mime_type,
        size_bytes=len(payload),
        checksum_sha256=checksum,
        role=role,
        width=width,
        height=height,
        duration_ms=item.get("duration_ms"),
        # Pack media is curated before it is handed over, so it enters approved
        # rather than sitting in the moderation queue.
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        is_prototype=False,
    )
    session.add(asset)
    session.flush()

    if asset.media_type == MediaType.IMAGE:
        media_service.record_fingerprint(session, asset=asset, payload=payload)

    media_service.record_provenance(
        session,
        asset=asset,
        generation_job_id=None,
        details={
            "source": "assets_pack",
            "pack_id": pack_id,
            "slug": slug,
            "license": item.get("license") or defaults.get("license"),
            "attribution": item.get("attribution") or defaults.get("attribution"),
        },
    )

    if consent:
        _record_consent(session, asset=asset, owner=owner, root=root, consent=consent)

    replaced = item.get("replaces_prototype")
    if replaced:
        count = _retire_prototype(session, marker=replaced, replacement=asset)
        report.replaced.append(f"{slug} 替换 {replaced} ({count} 处引用)")
    else:
        report.imported.append(slug)


def _record_consent(
    session: Session,
    *,
    asset: Asset,
    owner: User,
    root: Path,
    consent: dict[str, Any],
) -> None:
    evidence_asset_id: str | None = None
    evidence_file = consent.get("evidence_file")
    if evidence_file:
        evidence_path = resolve_file(root, evidence_file)
        payload = evidence_path.read_bytes()
        key = f"packs/consents/{asset.id}{evidence_path.suffix}"
        s3.put_object(key, payload, content_type="application/octet-stream")
        evidence = Asset(
            owner_user_id=owner.id,
            object_key=key,
            media_type=MediaType.IMAGE,
            mime_type="application/octet-stream",
            size_bytes=len(payload),
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
            role=AssetRole.CONSENT_EVIDENCE,
            moderation_status=ModerationStatus.APPROVED,
            # Evidence documents stay owner-only forever; they are proof, not
            # content.
            visibility=Visibility.PRIVATE,
        )
        session.add(evidence)
        session.flush()
        evidence_asset_id = evidence.id

    session.add(
        AssetConsent(
            asset_id=asset.id,
            consent_type="portrait",
            subject_reference=consent.get("subject_name", "unspecified"),
            evidence_asset_id=evidence_asset_id,
            status=ConsentStatus.VERIFIED if evidence_asset_id else ConsentStatus.DECLARED,
            expires_at=_parse_ts(consent.get("expires_at")),
        )
    )
    session.flush()


def _retire_prototype(session: Session, *, marker: str, replacement: Asset) -> int:
    """Repoints everything that referenced a placeholder at the real asset.

    Work versions store an asset id, so swapping the row the id points at is not
    an option — instead every reference is rewritten and the placeholder object
    is deleted from storage.
    """
    from app.models import GenerationJob, WorkVersion

    prototype = session.scalar(
        sa.select(Asset).where(
            Asset.is_prototype.is_(True), Asset.object_key.like(f"%{marker.split(':')[-1]}%")
        )
    )
    if prototype is None:
        return 0

    touched = 0
    versions = session.scalars(
        sa.select(WorkVersion).where(
            sa.or_(
                WorkVersion.primary_output_asset_id == prototype.id,
                WorkVersion.cover_asset_id == prototype.id,
            )
        )
    ).all()
    for version in versions:
        if version.primary_output_asset_id == prototype.id:
            version.primary_output_asset_id = replacement.id
        if version.cover_asset_id == prototype.id:
            version.cover_asset_id = replacement.id
        touched += 1

    jobs = session.scalars(
        sa.select(GenerationJob).where(GenerationJob.output_asset_id == prototype.id)
    ).all()
    for job in jobs:
        job.output_asset_id = replacement.id
        touched += 1

    session.flush()
    s3.delete_object(prototype.object_key)
    session.delete(prototype)
    session.flush()
    return touched


def _resolve_owner(session: Session, owner_email: str | None) -> User:
    if owner_email:
        user = session.scalar(sa.select(User).where(User.email == owner_email))
        if user is None:
            raise ManifestError(f"找不到指定的素材归属账号: {owner_email}")
        return user

    user = session.scalar(
        sa.select(User).where(User.roles.contains([UserRole.ADMIN.value])).order_by(User.created_at)
    )
    if user is None:
        raise ManifestError("库里没有管理员账号，先运行 seed 或用 --owner 指定归属账号。")
    return user


def _probe_dimensions(payload: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError) as exc:
        raise ManifestError("无法解析图片尺寸，请在清单里显式写 width/height。") from exc


def _media_type_for(mime_type: str) -> str:
    if mime_type.startswith("video/"):
        return MediaType.VIDEO
    if mime_type.startswith("audio/"):
        return MediaType.AUDIO
    return MediaType.IMAGE


def _parse_ts(value: str | None):  # type: ignore[no-untyped-def]
    if not value:
        return None
    import datetime as dt

    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="导入 assets-pack 素材")
    parser.add_argument(
        "--manifest",
        default="../assets-pack/manifest.json",
        help="清单路径，默认 ../assets-pack/manifest.json",
    )
    parser.add_argument("--owner", help="素材归属账号邮箱，默认取第一个管理员")
    parser.add_argument("--dry-run", action="store_true", help="只校验清单，不写库不上传")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).resolve()
    try:
        with session_scope() as session:
            report = run(
                session,
                manifest_path=manifest_path,
                owner_email=args.owner,
                dry_run=args.dry_run,
            )
            if not report.ok:
                # A partially-applied pack is worse than none: roll back so the
                # operator can fix the manifest and rerun.
                session.rollback()
    except ManifestError as exc:
        print(f"清单无法使用: {exc}", file=sys.stderr)
        return 2

    print(report.render())
    if args.dry_run:
        print("(dry-run，未写入任何数据)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
