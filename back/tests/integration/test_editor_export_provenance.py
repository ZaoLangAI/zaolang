"""A finished editor export carries an AI provenance claim, like generated output.

The browser runner writes the implicit AIGC label into the MP4's own metadata;
`exports.complete_export` records the matching server-side claim (unsigned —
C2PA signing is not implemented) so an exported cut is never an unlabelled
asset.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.editor import analysis as media_analysis
from app.domain.editor import exports as export_service
from app.domain.editor import state_machine as editor_sm
from app.domain.media import service as media_service
from app.models import ProvenanceManifest, User
from app.models.enums import EditorExportStatus
from app.storage import s3
from tests.integration.test_editor import _enable_editor, _open_cut, _ready_variant, _video_asset


def test_complete_export_records_an_unsigned_provenance_claim_once(
    client: TestClient,
    db: Session,
    author: User,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_editor(db, admin)
    opened = _open_cut(client, author, _video_asset(db, author))
    variant = _ready_variant(db, opened["cut"]["head_revision_id"], digest="p")
    export = export_service.queue_exports(
        db, user_id=author.id, variant_ids=[variant.id], operation_key="op-provenance"
    )[0]
    editor_sm.transition_export(db, export.id, EditorExportStatus.CLAIMED)
    editor_sm.transition_export(db, export.id, EditorExportStatus.ENCODING)

    payload = b"encoded cut bytes"
    presigned = export_service.presign_export_upload(
        db,
        user_id=author.id,
        export_id=export.id,
        filename="cut.mp4",
        mime_type="video/mp4",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
    )
    s3.put_object(presigned.upload_session.object_key, payload, content_type="video/mp4")
    # Stand-in for ffprobe reading a real MP4 (editor_export requires a duration).
    monkeypatch.setattr(media_analysis, "probe_bytes", lambda payload, mime: (1080, 1920, 1000))

    done = export_service.complete_export(
        db, user_id=author.id, export_id=export.id, upload_session_id=presigned.upload_session.id
    )
    assert done.status == EditorExportStatus.SUCCEEDED
    assert done.output_asset_id is not None

    manifest = media_service.provenance_for(db, done.output_asset_id)
    assert manifest is not None
    assert manifest.signature is None
    assert manifest.claim_json["zaolang.editor_export"]["export_id"] == export.id
    assert manifest.claim_json["instance_id"] == done.output_asset_id

    # A repeated complete is a no-op: still exactly one manifest for the asset.
    export_service.complete_export(
        db, user_id=author.id, export_id=export.id, upload_session_id=presigned.upload_session.id
    )
    count = db.scalar(
        select(func.count())
        .select_from(ProvenanceManifest)
        .where(ProvenanceManifest.asset_id == done.output_asset_id)
    )
    assert count == 1
