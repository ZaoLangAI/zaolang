"""Reference videos are re-encoded only when a provider would refuse them."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.media import service as media_service
from app.domain.media.conform import conform_reason, conform_reference_video
from app.models import User
from app.storage import s3

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg not installed",
)


def _clip(tmp_path: Path, name: str, *args: str) -> bytes:
    target = tmp_path / name
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=24:duration=2",
            *args,
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target.read_bytes()


def _probe(payload: bytes, tmp_path: Path) -> dict:
    path = tmp_path / "probe.bin"
    path.write_bytes(payload)
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return json.loads(proc.stdout)


def _video_stream(probe: dict) -> dict:
    return next(s for s in probe["streams"] if s["codec_type"] == "video")


def test_a_clip_providers_accept_is_left_alone(tmp_path: Path) -> None:
    payload = _clip(tmp_path, "ok.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p")
    assert conform_reason(_probe(payload, tmp_path)) is None
    assert conform_reference_video(payload) is None


def test_a_low_frame_rate_clip_is_resampled_to_a_constant_24fps(tmp_path: Path) -> None:
    payload = _clip(tmp_path, "slow.mp4", "-r", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p")
    source = _probe(payload, tmp_path)
    assert conform_reason(source) == "frame_rate"

    conformed = conform_reference_video(payload)
    assert conformed is not None and conformed.mime_type == "video/mp4"
    probe = _probe(conformed.payload, tmp_path)
    video = _video_stream(probe)
    assert video["codec_name"] == "h264"
    assert Fraction(video["r_frame_rate"]) == 24
    assert Fraction(video["avg_frame_rate"]) == 24
    assert float(probe["format"]["duration"]) == pytest.approx(
        float(source["format"]["duration"]), abs=1 / 24
    )
    assert conform_reason(probe) is None


def test_a_clip_stamped_at_the_providers_exact_floor_is_conformed(tmp_path: Path) -> None:
    """Chrome stamps a canvas recording 24000/1001 fps; one late frame puts
    its average under the provider's 23.976 floor."""
    payload = _clip(
        tmp_path, "ntsc.mp4", "-r", "24000/1001", "-c:v", "libx264", "-pix_fmt", "yuv420p"
    )
    assert conform_reason(_probe(payload, tmp_path)) == "frame_rate"
    conformed = conform_reference_video(payload)
    assert conformed is not None
    assert Fraction(_video_stream(_probe(conformed.payload, tmp_path))["avg_frame_rate"]) == 24


def test_a_webm_recording_becomes_an_h264_mp4(tmp_path: Path) -> None:
    payload = _clip(tmp_path, "rec.webm", "-c:v", "libvpx-vp9", "-b:v", "200k")
    assert conform_reason(_probe(payload, tmp_path)) == "container"

    conformed = conform_reference_video(payload)
    assert conformed is not None
    video = _video_stream(_probe(conformed.payload, tmp_path))
    assert video["codec_name"] == "h264"
    assert Fraction(video["avg_frame_rate"]) == 24


def test_an_uploaded_webm_reference_is_stored_as_the_conformed_mp4(
    db: Session, author: User, tmp_path: Path
) -> None:
    payload = _clip(tmp_path, "rec.webm", "-c:v", "libvpx-vp9", "-b:v", "200k")
    presigned = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="blocking_客厅#1.webm",
        mime_type="video/webm",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        purpose="generation_reference",
    )
    original_key = presigned.upload_session.object_key
    s3.put_object(original_key, payload, content_type="video/webm")

    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    assert asset.mime_type == "video/mp4"
    assert asset.object_key.endswith(".mp4")
    stored = s3.get_object(asset.object_key)
    assert asset.size_bytes == len(stored)
    assert asset.checksum_sha256 == hashlib.sha256(stored).hexdigest()
    assert asset.duration_ms == pytest.approx(2000, abs=100)
    if asset.object_key != original_key:
        assert s3.head_object(original_key) is None
