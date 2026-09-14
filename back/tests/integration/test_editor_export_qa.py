"""The post-export health check (`export-qa`): queued when an export
completes, run with real ffmpeg, and readable only by the export's owner."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.editor import analysis as media_analysis
from app.domain.editor import exports as export_service
from app.domain.editor import state_machine as editor_sm
from app.models import MediaAnalysis, User
from app.models.enums import EditorExportStatus, MediaAnalysisStatus
from app.storage import s3
from tests.conftest import auth_header, make_user
from tests.integration.test_editor import _enable_editor, _open_cut, _ready_variant, _video_asset

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)


def _encoded_clip(tmp_path: Path) -> bytes:
    """6s: black for the first 2s, a tone that goes silent from 3s."""
    out = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x240:d=6:r=15",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=6",
            "-vf",
            "drawbox=enable='lt(t,2)':x=0:y=0:w=iw:h=ih:c=black:t=fill",
            "-af",
            "volume=enable='gte(t,3)':volume=0",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ],
        check=True,
        timeout=60,
    )
    return out.read_bytes()


@needs_ffmpeg
def test_the_health_check_flags_black_frames_and_silence_in_a_real_export(
    db: Session, author: User, tmp_path: Path
) -> None:
    asset = _video_asset(db, author)
    s3.put_object(asset.object_key, _encoded_clip(tmp_path), content_type="video/mp4")
    row = media_analysis.enqueue_export_qa(db, asset_id=asset.id)

    result = media_analysis.run_export_qa(db, row.id)

    assert result.status == MediaAnalysisStatus.SUCCEEDED, result.failure_message
    by_code = {finding["code"]: finding for finding in result.findings_json}
    assert by_code["black_frames"]["at_seconds"] == pytest.approx(0, abs=0.2)
    assert by_code["long_silence"]["at_seconds"] == pytest.approx(3, abs=0.3)
    assert result.audio_json["has_audio"] is True
    assert isinstance(result.audio_json["integrated_lufs"], float)
    # Deduped per asset like every analyzer identity.
    assert media_analysis.enqueue_export_qa(db, asset_id=asset.id).id == row.id


def test_the_health_check_degrades_without_ffmpeg(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _video_asset(db, author)
    row = media_analysis.enqueue_export_qa(db, asset_id=asset.id)
    monkeypatch.setattr(media_analysis.shutil, "which", lambda name: None)

    result = media_analysis.run_export_qa(db, row.id)

    assert result.status == MediaAnalysisStatus.DEGRADED
    assert result.findings_json == []


def test_completing_an_export_queues_its_health_check_for_the_owner_only(
    client: TestClient,
    db: Session,
    author: User,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_editor(db, admin)
    opened = _open_cut(client, author, _video_asset(db, author))
    variant = _ready_variant(db, opened["cut"]["head_revision_id"], digest="q")
    export = export_service.queue_exports(
        db, user_id=author.id, variant_ids=[variant.id], operation_key="op-qa"
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
    monkeypatch.setattr(media_analysis, "probe_bytes", lambda payload, mime: (1080, 1920, 1000))
    sent: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "app.api.v1.editor.celery_app.send_task",
        lambda name, args=None, **kwargs: sent.append((name, args)),
    )

    response = client.post(
        f"/v1/editor-exports/{export.id}/complete",
        headers=auth_header(author),
        json={"upload_session_id": presigned.upload_session.id},
    )

    assert response.status_code == 200, response.text
    qa_id = response.json()["qa_operation_id"]
    assert qa_id.startswith("man_")
    assert ("app.workers.tasks.run_export_qa", [qa_id]) in sent

    row = db.get(MediaAnalysis, qa_id)
    assert row is not None
    row.status = MediaAnalysisStatus.SUCCEEDED
    row.findings_json = [
        {
            "code": "black_frames",
            "severity": "warning",
            "at_seconds": 0.0,
            "duration_seconds": 1.2,
            "value": None,
        }
    ]
    db.flush()
    owner_view = client.get(f"/v1/editor-operations/{qa_id}", headers=auth_header(author))
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["result"]["findings"][0]["code"] == "black_frames"

    stranger = make_user(db, email="qa-stranger@example.com", handle="qastranger")
    stranger_view = client.get(f"/v1/editor-operations/{qa_id}", headers=auth_header(stranger))
    assert stranger_view.status_code == 200, stranger_view.text
    assert stranger_view.json()["result"] == {}
