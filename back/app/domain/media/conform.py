"""Bring an uploaded reference video inside what video providers accept.

Providers validate a reference clip before they look at it — Seedance, for
one, refuses anything whose frame rate is outside 23.976–60 fps
(`content[1].video_url: video frame rate must be between 23.976 and 60
FPS`). A clip recorded in the browser breaks that easily: `MediaRecorder` on
a canvas stream (the blockout exporter's fallback when WebCodecs is
unavailable, e.g. any plain-HTTP deployment) writes a fragmented MP4 or a
WebM whose frames carry wall-clock timestamps rather than a fixed rate.

`conform_reference_video` probes the upload and, only when it would be
refused, re-encodes it to the most widely accepted shape: H.264 / yuv420p,
constant frame rate, `+faststart` MP4. A clip that already fits is returned
untouched, so ordinary phone and camera uploads are not re-encoded.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction

logger = logging.getLogger(__name__)

# Providers take 23.976–60 fps. The floor here sits just above 23.976: a
# canvas recording from Chrome is stamped exactly 24000/1001 and averages
# within a hair of it, so one late frame puts it under the provider's floor.
# Conforming genuine 23.976 footage to 24 costs nothing a reference cares
# about.
MIN_FPS = Fraction(2398, 100)
MAX_FPS = Fraction(60)
DEFAULT_FPS = 24
_ACCEPTED_FORMATS = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
_ACCEPTED_CODECS = frozenset({"h264", "hevc"})
_ACCEPTED_PIX_FMTS = frozenset({"yuv420p", "yuvj420p"})
_TIMEOUT_S = 180


@dataclass(frozen=True, slots=True)
class ConformedVideo:
    payload: bytes
    mime_type: str


def _rate(text: object) -> Fraction | None:
    try:
        value = Fraction(str(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _in_range(rate: Fraction | None) -> bool:
    return rate is not None and MIN_FPS <= rate <= MAX_FPS


def _probe(path: str) -> dict | None:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout.decode() or "{}")


def conform_reason(probe: dict) -> str | None:
    """Why a probed clip would be refused, or `None` when it fits."""
    video = next(
        (s for s in probe.get("streams") or [] if s.get("codec_type") == "video"),
        None,
    )
    if video is None:
        return "no_video_stream"
    formats = set(str(probe.get("format", {}).get("format_name", "")).split(","))
    if not formats & _ACCEPTED_FORMATS:
        return "container"
    if video.get("codec_name") not in _ACCEPTED_CODECS:
        return "codec"
    if video.get("pix_fmt") not in _ACCEPTED_PIX_FMTS:
        return "pixel_format"
    # Both rates must agree with the range: `r_frame_rate` is the stream's
    # nominal rate, `avg_frame_rate` frames/duration — a recorder clip can get
    # either one wrong, and providers do not say which they read.
    if not (
        _in_range(_rate(video.get("avg_frame_rate")))
        and _in_range(_rate(video.get("r_frame_rate")))
    ):
        return "frame_rate"
    if not probe.get("format", {}).get("duration"):
        return "duration"
    return None


def _target_fps(probe: dict) -> int:
    video = next(s for s in probe["streams"] if s.get("codec_type") == "video")
    rate = _rate(video.get("avg_frame_rate"))
    if _in_range(rate):
        return max(24, min(60, round(float(rate))))  # type: ignore[arg-type]
    return DEFAULT_FPS


def conform_reference_video(payload: bytes) -> ConformedVideo | None:
    """A re-encoded clip when `payload` would be refused, else `None`.

    Also `None` when ffmpeg is unavailable or the re-encode fails: the
    original upload is kept and the provider's own error still surfaces,
    exactly as before this step existed.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="conform-") as workdir:
        source = os.path.join(workdir, "source")
        target = os.path.join(workdir, "conformed.mp4")
        with open(source, "wb") as handle:
            handle.write(payload)
        probe = _probe(source)
        if probe is None:
            return None
        reason = conform_reason(probe)
        if reason in (None, "no_video_stream"):
            return None
        fps = _target_fps(probe)
        # `fps=` holds the last source frame for its whole duration; clamp to
        # the container's length so the guide stays as long as its segment.
        duration = probe.get("format", {}).get("duration")
        limit = ["-t", str(duration)] if duration else []
        proc = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                source,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                # `fps` resamples to a constant rate (duplicating or dropping
                # frames); `-fps_mode cfr` keeps the muxer from writing it back
                # as variable. Even dimensions are an H.264/yuv420p requirement.
                "-vf",
                f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                "-fps_mode",
                "cfr",
                "-r",
                str(fps),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                *limit,
                target,
            ],
            capture_output=True,
            check=False,
            timeout=_TIMEOUT_S,
        )
        if proc.returncode != 0 or not os.path.exists(target):
            logger.warning(
                "reference video conform failed (%s): %s",
                reason,
                proc.stderr.decode(errors="replace")[-500:],
            )
            return None
        with open(target, "rb") as handle:
            conformed = handle.read()
    logger.info("reference video conformed (%s) to %sfps H.264 MP4", reason, fps)
    return ConformedVideo(payload=conformed, mime_type="video/mp4")
