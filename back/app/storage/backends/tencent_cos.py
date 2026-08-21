"""Tencent Cloud Object Storage (COS) backend.

Selected instead of `MinioBackend` when `STORAGE_BACKEND=tencent_cos`. Uses
the native `cos-python-sdk-v5` SDK rather than boto3's S3-compat mode, so
bucket lifecycle/CORS/copy calls go through COS's own dict shapes (`Rule`
singular, `CORSRule` singular, `CopySource` with `Region`) — these are
translated to/from the AWS-shaped contract `StorageBackend` exposes so
callers never see the difference.
"""

from __future__ import annotations

import logging
import mimetypes
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from qcloud_cos import CosConfig, CosS3Client, CosServiceError

from app.config import get_settings
from app.domain.errors import NotFound
from app.storage.base import StorageBackend

logger = logging.getLogger(__name__)


def _domain_of(url: str) -> str | None:
    """CosConfig's `Domain` wants a bare host, not a scheme-qualified URL."""
    if not url:
        return None
    parsed = urlparse(url if "//" in url else f"//{url}")
    return parsed.netloc or parsed.path or None


@lru_cache
def _get_client() -> CosS3Client:
    settings = get_settings()
    config = CosConfig(
        Region=settings.cos_region,
        SecretId=settings.cos_secret_id,
        SecretKey=settings.cos_secret_key,
    )
    return CosS3Client(config)


@lru_cache
def _get_public_client() -> CosS3Client:
    """Signs URLs against the browser/provider-reachable domain.

    Only needed when `cos_public_endpoint_url` points at a CDN or custom
    domain different from COS's own region endpoint; otherwise identical to
    `_get_client()`.
    """
    settings = get_settings()
    domain = _domain_of(settings.cos_public_endpoint_url)
    if not domain:
        return _get_client()
    config = CosConfig(
        Region=settings.cos_region,
        SecretId=settings.cos_secret_id,
        SecretKey=settings.cos_secret_key,
        Domain=domain,
    )
    return CosS3Client(config)


def reset_client_cache() -> None:
    _get_client.cache_clear()
    _get_public_client.cache_clear()


class TencentCosBackend(StorageBackend):
    def active_bucket_name(self) -> str:
        return get_settings().cos_bucket

    def ensure_bucket(self) -> None:
        settings = get_settings()
        client = _get_client()
        bucket = settings.cos_bucket
        try:
            client.head_bucket(Bucket=bucket)
        except CosServiceError:
            client.create_bucket(Bucket=bucket)
        origins = [origin for origin in settings.cors_origins if origin]
        if origins:
            try:
                client.put_bucket_cors(
                    Bucket=bucket,
                    CORSConfiguration={
                        "CORSRule": [
                            {
                                "AllowedOrigin": origins,
                                "AllowedMethod": ["GET", "PUT", "HEAD"],
                                "AllowedHeader": ["*"],
                                "ExposeHeader": ["ETag", "Content-Length"],
                                "MaxAgeSeconds": 3600,
                            }
                        ]
                    },
                )
            except CosServiceError:
                logger.warning("could not apply COS CORS rules to %s", bucket)

    def head_bucket(self) -> None:
        _get_client().head_bucket(Bucket=get_settings().cos_bucket)

    def presign_put(self, object_key: str, *, content_type: str, expires_in: int) -> str:
        settings = get_settings()
        return _get_public_client().get_presigned_url(
            Bucket=settings.cos_bucket,
            Key=object_key,
            Method="PUT",
            Expired=expires_in,
            Headers={"Content-Type": content_type},
        )

    def presign_get(
        self, object_key: str, *, expires_in: int, download_name: str | None = None
    ) -> str:
        settings = get_settings()
        params: dict[str, Any] = {}
        if download_name:
            params["response-content-disposition"] = f'attachment; filename="{download_name}"'
        return _get_public_client().get_presigned_url(
            Bucket=settings.cos_bucket,
            Key=object_key,
            Method="GET",
            Expired=expires_in,
            Params=params,
        )

    def put_object(
        self, object_key: str, payload: bytes, *, content_type: str | None = None
    ) -> None:
        settings = get_settings()
        _get_client().put_object(
            Bucket=settings.cos_bucket,
            Key=object_key,
            Body=payload,
            ContentType=content_type
            or mimetypes.guess_type(object_key)[0]
            or "application/octet-stream",
        )

    def get_object(self, object_key: str) -> bytes:
        settings = get_settings()
        try:
            response = _get_client().get_object(Bucket=settings.cos_bucket, Key=object_key)
        except CosServiceError as exc:
            raise NotFound("对象不存在。") from exc
        body: bytes = response["Body"].get_raw_stream().read()
        return body

    def head_object(self, object_key: str) -> dict[str, Any] | None:
        settings = get_settings()
        try:
            response = _get_client().head_object(Bucket=settings.cos_bucket, Key=object_key)
        except CosServiceError:
            return None
        return {
            "size_bytes": int(response.get("Content-Length", 0)),
            "content_type": response.get("Content-Type", ""),
            "etag": str(response.get("ETag", "")).strip('"'),
        }

    def delete_object(self, object_key: str) -> None:
        settings = get_settings()
        _get_client().delete_object(Bucket=settings.cos_bucket, Key=object_key)

    def move_object(self, source_key: str, target_key: str) -> None:
        """Promotes a staged upload to its permanent location."""
        settings = get_settings()
        client = _get_client()
        client.copy_object(
            Bucket=settings.cos_bucket,
            Key=target_key,
            CopySource={
                "Bucket": settings.cos_bucket,
                "Key": source_key,
                "Region": settings.cos_region,
            },
        )
        client.delete_object(Bucket=settings.cos_bucket, Key=source_key)

    def bucket_usage(self) -> dict[str, Any]:
        """Object count, total size and a per-top-level-prefix breakdown."""
        settings = get_settings()
        client = _get_client()
        bucket = settings.cos_bucket
        total_bytes = 0
        count = 0
        by_prefix: dict[str, int] = {}
        marker = ""
        while True:
            page = client.list_objects(Bucket=bucket, Marker=marker, MaxKeys=1000)
            contents = page.get("Contents") or []
            if isinstance(contents, dict):
                contents = [contents]
            for item in contents:
                size = int(item.get("Size", 0))
                total_bytes += size
                count += 1
                prefix = str(item.get("Key", "")).split("/", 1)[0] or "(root)"
                by_prefix[prefix] = by_prefix.get(prefix, 0) + size
            if str(page.get("IsTruncated", "false")).lower() != "true":
                break
            marker = page.get("NextMarker") or (contents[-1]["Key"] if contents else "")
            if not marker:
                break
        return {"object_count": count, "total_bytes": total_bytes, "by_prefix": by_prefix}

    def lifecycle_rules(self) -> list[dict[str, Any]]:
        settings = get_settings()
        try:
            response = _get_client().get_bucket_lifecycle(Bucket=settings.cos_bucket)
        except CosServiceError:
            return []
        rules = response.get("Rule") or []
        if isinstance(rules, dict):
            rules = [rules]
        return list(rules)

    def put_lifecycle_rules(self, rules: list[dict[str, Any]]) -> None:
        settings = get_settings()
        _get_client().put_bucket_lifecycle(
            Bucket=settings.cos_bucket, LifecycleConfiguration={"Rule": rules}
        )
