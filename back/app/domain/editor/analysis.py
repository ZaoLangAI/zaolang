"""ffprobe-backed media analysis for editor sources."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.editor.time import TICKS_PER_SECOND
from app.domain.errors import NotFound, ValidationFailed
from app.models import Asset, MediaAnalysis
from app.models.enums import MediaAnalysisStatus, MediaType
from app.storage import s3

ANALYZER = "ffprobe"
ANALYZER_VERSION = "8"


def probe_bytes(payload: bytes, mime_type: str) -> tuple[int | None, int | None, int | None]:
    """Returns width, height, duration_ms. Missing ffprobe yields None duration."""
    if not mime_type.startswith("video/") and not mime_type.startswith("audio/"):
        return None, None, None
    if shutil.which("ffprobe") is None:
        return None, None, None
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "pipe:0",
        ],
        input=payload,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise ValidationFailed("无法探测该媒体文件。")
    data = json.loads(proc.stdout.decode() or "{}")
    width = height = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video":
            width = int(stream["width"]) if stream.get("width") else None
            height = int(stream["height"]) if stream.get("height") else None
            break
    duration_s = data.get("format", {}).get("duration")
    duration_ms = int(float(duration_s) * 1000) if duration_s else None
    return width, height, duration_ms


def enqueue(session: Session, *, asset_id: str) -> MediaAnalysis:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在。")
    existing = session.scalar(
        select(MediaAnalysis).where(
            MediaAnalysis.asset_id == asset_id,
            MediaAnalysis.analyzer == ANALYZER,
            MediaAnalysis.analyzer_version == ANALYZER_VERSION,
        )
    )
    if existing is not None:
        return existing
    row = MediaAnalysis(
        asset_id=asset_id,
        analyzer=ANALYZER,
        analyzer_version=ANALYZER_VERSION,
        status=MediaAnalysisStatus.QUEUED,
    )
    session.add(row)
    session.flush()
    return row


def run_analysis(session: Session, analysis_id: str) -> MediaAnalysis:
    row = session.get(MediaAnalysis, analysis_id)
    if row is None:
        raise NotFound("媒体分析不存在。")
    asset = session.get(Asset, row.asset_id)
    if asset is None:
        row.status = MediaAnalysisStatus.FAILED
        row.failure_message = "素材已删除。"
        session.flush()
        return row
    row.status = MediaAnalysisStatus.RUNNING
    session.flush()
    try:
        payload = s3.get_object(asset.object_key)
        width, height, duration_ms = probe_bytes(payload, asset.mime_type)
        if duration_ms and not asset.duration_ms:
            asset.duration_ms = duration_ms
        if width and not asset.width:
            asset.width = width
        if height and not asset.height:
            asset.height = height
        duration_ticks = None if duration_ms is None else duration_ms * TICKS_PER_SECOND // 1000
        audio = {"channels": None, "has_audio": asset.media_type != MediaType.IMAGE}
        result = {
            "width": width,
            "height": height,
            "duration_ms": duration_ms,
            "mime_type": asset.mime_type,
        }
        row.audio_json = audio
        row.shots_json = []
        row.focus_json = {}
        row.transcript_json = {}
        row.duration_ticks = duration_ticks
        row.result_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row.status = (
            MediaAnalysisStatus.DEGRADED
            if shutil.which("ffprobe") is None
            else MediaAnalysisStatus.SUCCEEDED
        )
        if row.status == MediaAnalysisStatus.DEGRADED:
            row.failure_message = "ffprobe 不可用，已跳过深度分析。"
    except Exception as exc:
        row.status = MediaAnalysisStatus.FAILED
        row.failure_message = str(exc)
    session.flush()
    return row


def summary_for(session: Session, asset_id: str) -> dict[str, Any] | None:
    row = session.scalar(
        select(MediaAnalysis)
        .where(MediaAnalysis.asset_id == asset_id)
        .order_by(MediaAnalysis.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "duration_ticks": row.duration_ticks,
        "shots": row.shots_json,
        "transcript": row.transcript_json,
        "audio": row.audio_json,
        "analyzer": row.analyzer,
        "analyzer_version": row.analyzer_version,
    }
