"""S3-compatible object storage (MinIO locally).

The bucket is private. Browsers never receive a permanent object URL; they get
a short-lived signed URL minted only after an ownership or visibility check.
"""

from __future__ import annotations

import mimetypes
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings
from app.domain.errors import NotFound

# Only these can be uploaded by users. Anything else is rejected before a
# presigned URL is issued, so the bucket cannot receive arbitrary payloads.
ALLOWED_UPLOAD_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

MAX_UPLOAD_BYTES: dict[str, int] = {
    "generation_reference": 32 * 1024 * 1024,
    "avatar": 4 * 1024 * 1024,
    "profile_cover": 12 * 1024 * 1024,
    "consent_evidence": 16 * 1024 * 1024,
}

# Each purpose is confined to its own prefix so a signed URL for an avatar can
# never be replayed to overwrite generated output.
PURPOSE_PREFIXES: dict[str, str] = {
    "generation_reference": "staging/references",
    "avatar": "staging/avatars",
    "profile_cover": "staging/covers",
    "consent_evidence": "staging/consents",
}


@lru_cache
def get_client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache
def get_public_client() -> Any:
    """Signs URLs against the browser-reachable endpoint.

    Inside Docker the API talks to `minio:9000` while the browser needs
    `localhost:9000`; signing with the wrong host produces a signature the
    browser cannot use.
    """
    settings = get_settings()
    if settings.s3_public_endpoint_url == settings.s3_endpoint_url:
        return get_client()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_public_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def reset_client_cache() -> None:
    get_client.cache_clear()
    get_public_client.cache_clear()


def ensure_bucket() -> None:
    settings = get_settings()
    client = get_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def head_bucket() -> None:
    """Liveness probe for the object store. Raises if unreachable."""
    get_client().head_bucket(Bucket=get_settings().s3_bucket)


def presign_put(object_key: str, *, content_type: str, expires_in: int) -> str:
    settings = get_settings()
    return get_public_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def presign_get(object_key: str, *, expires_in: int, download_name: str | None = None) -> str:
    settings = get_settings()
    params: dict[str, Any] = {"Bucket": settings.s3_bucket, "Key": object_key}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return get_public_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires_in
    )


def put_object(object_key: str, payload: bytes, *, content_type: str | None = None) -> None:
    settings = get_settings()
    get_client().put_object(
        Bucket=settings.s3_bucket,
        Key=object_key,
        Body=payload,
        ContentType=content_type
        or mimetypes.guess_type(object_key)[0]
        or "application/octet-stream",
    )


def get_object(object_key: str) -> bytes:
    settings = get_settings()
    try:
        response = get_client().get_object(Bucket=settings.s3_bucket, Key=object_key)
    except ClientError as exc:
        raise NotFound("对象不存在。") from exc
    body: bytes = response["Body"].read()
    return body


def head_object(object_key: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        response = get_client().head_object(Bucket=settings.s3_bucket, Key=object_key)
    except ClientError:
        return None
    return {
        "size_bytes": int(response.get("ContentLength", 0)),
        "content_type": response.get("ContentType", ""),
        "etag": str(response.get("ETag", "")).strip('"'),
    }


def delete_object(object_key: str) -> None:
    settings = get_settings()
    get_client().delete_object(Bucket=settings.s3_bucket, Key=object_key)


def move_object(source_key: str, target_key: str) -> None:
    """Promotes a staged upload to its permanent location."""
    settings = get_settings()
    client = get_client()
    client.copy_object(
        Bucket=settings.s3_bucket,
        CopySource={"Bucket": settings.s3_bucket, "Key": source_key},
        Key=target_key,
    )
    client.delete_object(Bucket=settings.s3_bucket, Key=source_key)


def bucket_usage() -> dict[str, Any]:
    """Object count, total size and a per-top-level-prefix breakdown.

    The breakdown is what tells an operator whether growth is coming from
    generated output or from abandoned staging uploads.
    """
    settings = get_settings()
    paginator = get_client().get_paginator("list_objects_v2")
    total_bytes = 0
    count = 0
    by_prefix: dict[str, int] = {}
    for page in paginator.paginate(Bucket=settings.s3_bucket):
        for item in page.get("Contents", []):
            size = int(item.get("Size", 0))
            total_bytes += size
            count += 1
            prefix = str(item.get("Key", "")).split("/", 1)[0] or "(root)"
            by_prefix[prefix] = by_prefix.get(prefix, 0) + size
    return {"object_count": count, "total_bytes": total_bytes, "by_prefix": by_prefix}


def lifecycle_rules() -> list[dict[str, Any]]:
    settings = get_settings()
    try:
        response = get_client().get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)
    except ClientError:
        return []
    rules: list[dict[str, Any]] = response.get("Rules", [])
    return rules


def put_lifecycle_rules(rules: list[dict[str, Any]]) -> None:
    settings = get_settings()
    get_client().put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket, LifecycleConfiguration={"Rules": rules}
    )
