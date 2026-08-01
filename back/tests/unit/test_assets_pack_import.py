"""assets-pack manifest contract and importer."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, AssetConsent, User
from app.models.enums import UserRole, Visibility
from app.scripts import import_assets_pack as importer
from app.storage import s3
from tests.conftest import make_user


def _write_png(path: Path, colour: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), colour).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    _write_png(tmp_path / "media" / "hero.png", (12, 34, 56))
    manifest = {
        "version": 1,
        "pack_id": "test-pack",
        "defaults": {"license": "CC-BY-4.0", "attribution": "测试"},
        "items": [
            {
                "slug": "hero",
                "file": "media/hero.png",
                "mime_type": "image/png",
                "role": "generation_output",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture
def pack_owner(db: Session) -> User:
    return make_user(
        db,
        email="packowner@example.com",
        handle="packowner",
        roles=[UserRole.USER.value, UserRole.ADMIN.value],
    )


def test_an_unknown_manifest_version_is_refused(tmp_path: Path) -> None:
    """Silently importing a manifest written for a different contract would
    produce plausible-looking but wrong assets."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": 99, "items": []}), encoding="utf-8")

    with pytest.raises(importer.ManifestError):
        importer.load_manifest(path)


def test_duplicate_slugs_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"version": 1, "items": [{"slug": "a"}, {"slug": "a"}]}), encoding="utf-8"
    )
    with pytest.raises(importer.ManifestError):
        importer.load_manifest(path)


def test_a_path_outside_the_pack_is_refused(tmp_path: Path) -> None:
    """A manifest must not be able to read arbitrary files off the operator's
    machine."""
    with pytest.raises(importer.ManifestError):
        importer.resolve_file(tmp_path, "../../../etc/passwd")


def test_the_shipped_example_manifest_matches_the_contract() -> None:
    example = Path(__file__).resolve().parents[3] / "assets-pack" / "manifest.example.json"
    manifest = importer.load_manifest(example)
    assert {item["slug"] for item in manifest["items"]}
    for item in manifest["items"]:
        assert item["role"] in importer.VALID_ROLES
        assert item["mime_type"] in s3.ALLOWED_UPLOAD_MIME_TYPES


def test_a_dry_run_writes_nothing(db: Session, pack: Path, pack_owner: User) -> None:
    before = db.scalar(select(Asset).where(Asset.object_key.like("packs/%")))
    report = importer.run(db, manifest_path=pack, owner_email=pack_owner.email, dry_run=True)
    assert report.ok
    assert db.scalar(select(Asset).where(Asset.object_key.like("packs/%"))) == before


def test_importing_registers_a_public_non_prototype_asset(
    db: Session, pack: Path, pack_owner: User
) -> None:
    report = importer.run(db, manifest_path=pack, owner_email=pack_owner.email)
    assert report.ok, report.errors

    asset = db.scalar(select(Asset).where(Asset.object_key == "packs/test-pack/hero.png"))
    assert asset is not None
    assert asset.is_prototype is False
    assert asset.visibility == Visibility.PUBLIC_VIEW_ONLY
    assert asset.width == 48


def test_reimporting_the_same_pack_is_idempotent(db: Session, pack: Path, pack_owner: User) -> None:
    importer.run(db, manifest_path=pack, owner_email=pack_owner.email)
    second = importer.run(db, manifest_path=pack, owner_email=pack_owner.email)

    assert second.skipped
    assert not second.imported
    count = len(
        list(db.scalars(select(Asset).where(Asset.object_key == "packs/test-pack/hero.png")))
    )
    assert count == 1


def test_imported_media_carries_provenance(db: Session, pack: Path, pack_owner: User) -> None:
    importer.run(db, manifest_path=pack, owner_email=pack_owner.email)
    asset = db.scalar(select(Asset).where(Asset.object_key == "packs/test-pack/hero.png"))
    assert asset is not None

    from app.domain.media import service as media_service

    manifest = media_service.provenance_for(db, asset.id)
    assert manifest is not None
    assert manifest.claim_json["source"] == "assets_pack"
    assert manifest.claim_json["license"] == "CC-BY-4.0"


def test_a_reference_of_a_real_person_without_consent_is_rejected(
    db: Session, tmp_path: Path, pack_owner: User
) -> None:
    """Importing first and chasing paperwork later is exactly the failure mode
    the consent record exists to prevent."""
    _write_png(tmp_path / "media" / "portrait.png", (99, 99, 99))
    manifest = {
        "version": 1,
        "pack_id": "risky",
        "items": [
            {
                "slug": "portrait",
                "file": "media/portrait.png",
                "mime_type": "image/png",
                "role": "generation_reference",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    report = importer.run(db, manifest_path=path, owner_email=pack_owner.email)
    assert not report.ok
    assert "consent" in report.errors[0]


def test_consent_evidence_is_stored_privately(
    db: Session, tmp_path: Path, pack_owner: User
) -> None:
    _write_png(tmp_path / "media" / "portrait.png", (33, 44, 55))
    (tmp_path / "consent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "consent" / "release.pdf").write_bytes(b"%PDF-1.4 signed release")

    manifest = {
        "version": 1,
        "pack_id": "consented",
        "items": [
            {
                "slug": "portrait",
                "file": "media/portrait.png",
                "mime_type": "image/png",
                "role": "generation_reference",
                "consent": {
                    "subject_name": "示例模特",
                    "evidence_file": "consent/release.pdf",
                },
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    report = importer.run(db, manifest_path=path, owner_email=pack_owner.email)
    assert report.ok, report.errors

    asset = db.scalar(select(Asset).where(Asset.object_key == "packs/consented/portrait.png"))
    assert asset is not None
    consent = db.scalar(select(AssetConsent).where(AssetConsent.asset_id == asset.id))
    assert consent is not None
    assert consent.evidence_asset_id is not None

    evidence = db.get(Asset, consent.evidence_asset_id)
    assert evidence is not None
    assert evidence.visibility == Visibility.PRIVATE


def test_one_broken_item_does_not_abort_the_rest_of_the_pack(
    db: Session, tmp_path: Path, pack_owner: User
) -> None:
    _write_png(tmp_path / "media" / "good.png", (1, 2, 3))
    manifest = {
        "version": 1,
        "pack_id": "mixed",
        "items": [
            {
                "slug": "missing",
                "file": "media/absent.png",
                "mime_type": "image/png",
                "role": "generation_output",
            },
            {
                "slug": "good",
                "file": "media/good.png",
                "mime_type": "image/png",
                "role": "generation_output",
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    report = importer.run(db, manifest_path=path, owner_email=pack_owner.email)
    assert report.errors and "missing" in report.errors[0]
    assert "good" in report.imported
