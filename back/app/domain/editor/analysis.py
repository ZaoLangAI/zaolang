"""ffprobe-backed media analysis, and ASR transcription, for editor sources."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.editor.time import TICKS_PER_SECOND
from app.domain.errors import NotFound, ValidationFailed
from app.models import Asset, MediaAnalysis
from app.models.enums import MediaAnalysisStatus, MediaType
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.providers.aihubmix_media import media_client_base, media_request_path
from app.storage import s3

ANALYZER = "ffprobe"
ANALYZER_VERSION = "8"

# A second, independent `MediaAnalysis` analyzer identity for the same asset
# — the table's `(asset_id, analyzer, analyzer_version)` unique constraint is
# deliberately built to hold more than one analyzer per asset, so this needs
# no schema change.
ASR_ANALYZER = "whisper-asr"
ASR_ANALYZER_VERSION = "1"


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


def enqueue_transcription(session: Session, *, asset_id: str) -> MediaAnalysis:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在。")
    if asset.media_type not in {MediaType.VIDEO, MediaType.AUDIO}:
        raise ValidationFailed("只能对视频或音频素材发起转写。")
    existing = session.scalar(
        select(MediaAnalysis).where(
            MediaAnalysis.asset_id == asset_id,
            MediaAnalysis.analyzer == ASR_ANALYZER,
            MediaAnalysis.analyzer_version == ASR_ANALYZER_VERSION,
        )
    )
    if existing is not None:
        return existing
    row = MediaAnalysis(
        asset_id=asset_id,
        analyzer=ASR_ANALYZER,
        analyzer_version=ASR_ANALYZER_VERSION,
        status=MediaAnalysisStatus.QUEUED,
    )
    session.add(row)
    session.flush()
    return row


def _resolve_asr_endpoint(session: Session) -> tuple[str, str, int] | None:
    """Reuses any enabled media endpoint that also serves `audio_generation`.

    Deliberately *not* routed through `app.agents.router` — that machinery
    exists to have an LLM pick among cost/latency-scored candidates for a
    user-initiated generation job; transcription is a deterministic analysis
    side-effect of an asset that already exists, with no job/credit-ledger
    semantics and nothing to choose between. Reusing the audio-generation
    endpoint's credentials is safe because AiHubMix-style gateways serve
    `/v1/audio/speech` (TTS) and `/v1/audio/transcriptions` (ASR) from the
    same account and base URL.
    """
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    for endpoint in config.endpoints.values():
        if endpoint.enabled and endpoint.kind == "media" and "audio_generation" in endpoint.capabilities:
            return endpoint.base_url, endpoint.api_key, endpoint.timeout_ms
    return None


def _call_asr(
    *, base_url: str, api_key: str, timeout_ms: int, payload: bytes, mime_type: str, filename: str
) -> dict[str, Any]:
    with httpx.Client(
        base_url=media_client_base(base_url),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_ms / 1000,
    ) as client:
        response = client.post(
            media_request_path(base_url, "/v1/audio/transcriptions"),
            data={"model": "whisper-1", "response_format": "verbose_json"},
            files={"file": (filename, payload, mime_type)},
        )
        response.raise_for_status()
        return response.json()


def run_transcription(session: Session, analysis_id: str) -> MediaAnalysis:
    """Populates `transcript_json` for real — what `run_analysis` (the
    ffprobe path) has always left as `{}` for this analyzer identity.
    """
    row = session.get(MediaAnalysis, analysis_id)
    if row is None:
        raise NotFound("媒体转写不存在。")
    asset = session.get(Asset, row.asset_id)
    if asset is None:
        row.status = MediaAnalysisStatus.FAILED
        row.failure_message = "素材已删除。"
        session.flush()
        return row
    row.status = MediaAnalysisStatus.RUNNING
    session.flush()
    try:
        endpoint = _resolve_asr_endpoint(session)
        if endpoint is None:
            raise ValidationFailed("没有可用的语音转写服务端点。")
        base_url, api_key, timeout_ms = endpoint
        payload = s3.get_object(asset.object_key)
        filename = asset.object_key.rsplit("/", 1)[-1]
        raw = _call_asr(
            base_url=base_url,
            api_key=api_key,
            timeout_ms=timeout_ms,
            payload=payload,
            mime_type=asset.mime_type,
            filename=filename,
        )
        segments = [
            {
                "start_ms": int(float(segment.get("start", 0)) * 1000),
                "end_ms": int(float(segment.get("end", 0)) * 1000),
                "text": str(segment.get("text", "")).strip(),
            }
            for segment in raw.get("segments") or []
            if str(segment.get("text", "")).strip()
        ]
        row.transcript_json = {"language": raw.get("language"), "segments": segments}
        row.result_hash = hashlib.sha256(
            json.dumps(row.transcript_json, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row.status = MediaAnalysisStatus.SUCCEEDED
    except Exception as exc:
        row.status = MediaAnalysisStatus.FAILED
        row.failure_message = str(exc)
    session.flush()
    return row
