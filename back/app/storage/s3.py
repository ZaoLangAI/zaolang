"""Object storage facade.

The bucket is private. Browsers never receive a permanent object URL; they get
a short-lived signed URL minted only after an ownership or visibility check.

Every function here delegates to whichever `StorageBackend` `settings.
storage_backend` selects (MinIO or Tencent COS — see `app/storage/factory.py`
and `app/storage/backends/`). Callers throughout the domain/API/worker layers
only ever import from this module, never a backend directly, so a backend
swap changes nothing outside `app/storage/`.
"""

from __future__ import annotations

from typing import Any

from app.storage.factory import get_backend, reset_backend_cache

# Only these can be uploaded by users. Anything else is rejected before a
# presigned URL is issued, so the bucket cannot receive arbitrary payloads.
ALLOWED_UPLOAD_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    # Voice-clone reference samples only (`voice_sample` purpose) — no other
    # purpose accepts audio today.
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
}

MAX_UPLOAD_BYTES: dict[str, int] = {
    "generation_reference": 32 * 1024 * 1024,
    "avatar": 4 * 1024 * 1024,
    "profile_cover": 12 * 1024 * 1024,
    "consent_evidence": 16 * 1024 * 1024,
    "learn_media": 12 * 1024 * 1024,
    "style_gallery_cover": 8 * 1024 * 1024,
    "series_logo": 4 * 1024 * 1024,
    "episode_preview": 4 * 1024 * 1024,
    "editor_source": 256 * 1024 * 1024,
    "editor_export": 256 * 1024 * 1024,
    "caption": 4 * 1024 * 1024,
    "font": 8 * 1024 * 1024,
    # A 3-minute reference clip (the "视频解析" tool's own cap — see
    # `app.domain.media.service.VIDEO_ANALYSIS_MAX_DURATION_MS`) routinely
    # exceeds `generation_reference`'s 32MB, which is sized for a still
    # reference image or a very short generation-reference clip instead.
    "video_analysis_source": 150 * 1024 * 1024,
    # A short voice-clone reference sample (a few seconds to ~1 minute of
    # speech) — nowhere near a video's size, but its own purpose because
    # `generation_reference`'s MIME gate is image/video only.
    "voice_sample": 8 * 1024 * 1024,
}

# Each purpose is confined to its own prefix so a signed URL for an avatar can
# never be replayed to overwrite generated output.
PURPOSE_PREFIXES: dict[str, str] = {
    "generation_reference": "staging/references",
    "avatar": "staging/avatars",
    "profile_cover": "staging/covers",
    "consent_evidence": "staging/consents",
    "learn_media": "staging/learn-media",
    "style_gallery_cover": "staging/style-gallery",
    "series_logo": "staging/series-logos",
    "episode_preview": "staging/episode-previews",
    "editor_source": "staging/editor-source",
    "editor_export": "staging/editor-export",
    "caption": "staging/captions",
    "font": "staging/fonts",
    "video_analysis_source": "staging/video-analysis-sources",
    "voice_sample": "staging/voice-samples",
}


def reset_client_cache() -> None:
    reset_backend_cache()


def active_bucket_name() -> str:
    return get_backend().active_bucket_name()


def ensure_bucket() -> None:
    get_backend().ensure_bucket()


def head_bucket() -> None:
    """Liveness probe for the object store. Raises if unreachable."""
    get_backend().head_bucket()


def presign_put(object_key: str, *, content_type: str, expires_in: int) -> str:
    return get_backend().presign_put(object_key, content_type=content_type, expires_in=expires_in)


def presign_get(object_key: str, *, expires_in: int, download_name: str | None = None) -> str:
    return get_backend().presign_get(object_key, expires_in=expires_in, download_name=download_name)


def put_object(object_key: str, payload: bytes, *, content_type: str | None = None) -> None:
    get_backend().put_object(object_key, payload, content_type=content_type)


def get_object(object_key: str) -> bytes:
    return get_backend().get_object(object_key)


def head_object(object_key: str) -> dict[str, Any] | None:
    return get_backend().head_object(object_key)


def delete_object(object_key: str) -> None:
    get_backend().delete_object(object_key)


def move_object(source_key: str, target_key: str) -> None:
    """Promotes a staged upload to its permanent location."""
    get_backend().move_object(source_key, target_key)


def bucket_usage() -> dict[str, Any]:
    """Object count, total size and a per-top-level-prefix breakdown.

    The breakdown is what tells an operator whether growth is coming from
    generated output or from abandoned staging uploads.
    """
    return get_backend().bucket_usage()


def lifecycle_rules() -> list[dict[str, Any]]:
    return get_backend().lifecycle_rules()


def put_lifecycle_rules(rules: list[dict[str, Any]]) -> None:
    get_backend().put_lifecycle_rules(rules)
