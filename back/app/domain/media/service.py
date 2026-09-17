"""Upload lifecycle and content integrity.

An upload is a two-step handshake. `presign` records exactly what the client
promised — user, key, MIME type, size, checksum, purpose — and `complete`
verifies the stored object against that promise before an `Asset` exists. A
signed URL therefore cannot be replayed to smuggle in a different file, a
different type, or a file belonging to a different purpose.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import imagehash
from botocore.exceptions import ClientError
from PIL import Image, UnidentifiedImageError
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.licensing import service as licensing
from app.models import (
    Asset,
    ContentFingerprint,
    Draft,
    DramaEpisode,
    GenerationJob,
    LineageEdge,
    Profile,
    ProvenanceManifest,
    Series,
    UploadSession,
    Work,
    WorkVersion,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    AssetRole,
    ImageAssetKind,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from app.providers.base import ProviderReference
from app.storage import s3

logger = logging.getLogger(__name__)

# Matches the "视频解析" product requirement that a source clip is at most
# 3 minutes; enforced here (not just client-side) since asset duration is
# only known once ffprobe has run during upload completion.
VIDEO_ANALYSIS_MAX_DURATION_MS = 180_000

PURPOSE_TO_ROLE: dict[str, AssetRole] = {
    "generation_reference": AssetRole.GENERATION_REFERENCE,
    "avatar": AssetRole.AVATAR,
    "profile_cover": AssetRole.PROFILE_COVER,
    "consent_evidence": AssetRole.CONSENT_EVIDENCE,
    "learn_media": AssetRole.LEARN_MEDIA,
    "style_gallery_cover": AssetRole.COVER,
    "series_logo": AssetRole.COVER,
    "episode_preview": AssetRole.COVER,
    # Ends up in `reference_asset_ids` exactly like `generation_reference` —
    # it only needs its own upload `purpose` for the bigger size ceiling a
    # 3-minute clip needs (see `s3.MAX_UPLOAD_BYTES`).
    "video_analysis_source": AssetRole.GENERATION_REFERENCE,
    # Same reasoning as `video_analysis_source` above: a voice-clone sample
    # ends up in `reference_asset_ids` (as the `AUDIO_GENERATION` job's
    # `reference_asset_id` extra) exactly like any other reference asset —
    # it only needs its own purpose for the audio MIME gate + size ceiling.
    "voice_sample": AssetRole.GENERATION_REFERENCE,
    "editor_source": AssetRole.EDITOR_SOURCE,
    "editor_export": AssetRole.EDITOR_EXPORT,
    "caption": AssetRole.EDITOR_CAPTION,
    "font": AssetRole.EDITOR_FONT,
}

# Two images within this Hamming distance are treated as the same content.
DUPLICATE_HAMMING_THRESHOLD = 6


@dataclass(slots=True)
class PresignedUpload:
    upload_session: UploadSession
    upload_url: str
    required_headers: dict[str, str]


def presign_upload(
    session: Session,
    *,
    user_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    checksum_sha256: str,
    purpose: str,
    depicts_real_person: bool = False,
) -> PresignedUpload:
    """`depicts_real_person` is the uploader's own declaration that an image
    or video shows a real person; it rides on the upload session and lands on
    the `Asset`, where `consent.assert_reference_consents` then requires a
    portrait consent before the asset may feed a generation job."""
    settings = get_settings()

    extension = s3.ALLOWED_UPLOAD_MIME_TYPES.get(mime_type)
    if extension is None:
        raise ValidationFailed(f"不支持的文件类型: {mime_type}", mime_type=mime_type)
    if purpose not in s3.PURPOSE_PREFIXES:
        raise ValidationFailed(f"不支持的用途: {purpose}", purpose=purpose)

    limit = s3.MAX_UPLOAD_BYTES[purpose]
    if size_bytes > limit:
        raise ValidationFailed(
            f"文件超过 {limit // (1024 * 1024)}MB 上限。", size_bytes=size_bytes, limit=limit
        )
    if purpose in (
        "avatar",
        "profile_cover",
        "learn_media",
        "style_gallery_cover",
        "series_logo",
        "episode_preview",
    ) and not mime_type.startswith("image/"):
        raise ValidationFailed("头像、封面与学习内容配图必须是图片。", mime_type=mime_type)
    if purpose == "video_analysis_source" and not mime_type.startswith("video/"):
        raise ValidationFailed("视频解析的参考素材必须是视频。", mime_type=mime_type)
    if purpose == "voice_sample" and not mime_type.startswith("audio/"):
        raise ValidationFailed("声音克隆参考样本必须是音频。", mime_type=mime_type)

    # The key embeds the owner, so an object's directory alone proves who may
    # write to it.
    object_key = f"{s3.PURPOSE_PREFIXES[purpose]}/{user_id}/{new_id('obj')}{extension}"
    expires_at = utcnow() + dt.timedelta(seconds=settings.upload_url_ttl_seconds)

    upload_session = UploadSession(
        user_id=user_id,
        object_key=object_key,
        purpose=purpose,
        mime_type=mime_type,
        declared_size_bytes=size_bytes,
        declared_checksum_sha256=checksum_sha256,
        expires_at=expires_at,
        # Only an image or video can show a person; ignored for anything else.
        depicts_real_person=depicts_real_person and mime_type.startswith(("image/", "video/")),
    )
    session.add(upload_session)
    session.flush()

    url = s3.presign_put(
        object_key, content_type=mime_type, expires_in=settings.upload_url_ttl_seconds
    )
    return PresignedUpload(
        upload_session=upload_session,
        upload_url=url,
        required_headers={"Content-Type": mime_type},
    )


def complete_upload(session: Session, *, user_id: str, upload_session_id: str) -> Asset:
    """Verifies the stored object and creates the asset."""
    upload = session.get(UploadSession, upload_session_id)
    if upload is None:
        raise NotFound("上传会话不存在。")
    if upload.user_id != user_id:
        raise Forbidden("不能完成他人的上传。")
    if upload.completed_at is not None:
        existing = session.get(Asset, upload.asset_id) if upload.asset_id else None
        if existing is not None:
            return existing
        raise Conflict("上传会话已结束。")
    if upload.expires_at < utcnow():
        raise Conflict("上传链接已过期，请重新发起。")

    head = s3.head_object(upload.object_key)
    if head is None:
        raise Conflict("尚未检测到已上传的文件。")
    if head["size_bytes"] != upload.declared_size_bytes:
        raise ValidationFailed(
            "文件大小与申请时不一致。",
            declared=upload.declared_size_bytes,
            actual=head["size_bytes"],
        )

    payload = s3.get_object(upload.object_key)
    actual_checksum = hashlib.sha256(payload).hexdigest()
    if actual_checksum != upload.declared_checksum_sha256:
        # Refuse rather than trust the bytes: the promise was part of what the
        # signature authorised.
        s3.delete_object(upload.object_key)
        raise ValidationFailed("文件校验和与申请时不一致。")

    width, height, media_type = _probe(payload, upload.mime_type)
    duration_ms = None
    if media_type in {MediaType.VIDEO, MediaType.AUDIO}:
        from app.domain.editor.analysis import probe_bytes

        probed_w, probed_h, duration_ms = probe_bytes(payload, upload.mime_type)
        width = width or probed_w
        height = height or probed_h
        if upload.purpose == "editor_export" and duration_ms is None and shutil.which("ffprobe"):
            raise ValidationFailed("导出文件无法通过 ffprobe 校验。")

    asset = Asset(
        owner_user_id=user_id,
        object_key=upload.object_key,
        media_type=media_type,
        mime_type=upload.mime_type,
        size_bytes=head["size_bytes"],
        checksum_sha256=actual_checksum,
        role=PURPOSE_TO_ROLE[upload.purpose],
        width=width,
        height=height,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.PENDING,
        visibility=Visibility.PRIVATE,
        depicts_real_person=upload.depicts_real_person,
    )
    session.add(asset)
    session.flush()

    upload.completed_at = utcnow()
    upload.asset_id = asset.id
    session.flush()

    if media_type == MediaType.IMAGE:
        record_fingerprint(session, asset=asset, payload=payload)
    return asset


def object_keys_for(session: Session, *, asset_ids: Sequence[str]) -> list[str]:
    """Resolves reference asset ids to storage keys for a provider request.

    Order is preserved and missing ids are skipped rather than raising: by the
    time the pipeline runs, ownership was already checked at submission, so a
    gap here means the asset was deleted, not a request to reject.
    """
    if not asset_ids:
        return []
    rows = session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
    by_id = {asset.id: asset.object_key for asset in rows}
    return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]


# Character sheets and scene plates belong in the character/scene libraries,
# not the drama editor's footage rail. Hidden in SQL so they cannot fill the
# `limit=40` page. Videos (including `character_action`) stay visible.
_EDITOR_LIBRARY_HIDDEN_ASSET_KINDS: tuple[str, ...] = (
    ImageAssetKind.CHARACTER.value,
    ImageAssetKind.SCENE.value,
)


def list_owned_media(
    session: Session,
    *,
    user_id: str,
    media_type: MediaType | None,
    limit: int,
) -> list[Asset]:
    """Lists a user's own usable editing source material.

    Scoped to `GENERATION_OUTPUT`/`EDITOR_SOURCE` roles only, so an avatar,
    consent-evidence, or learn-media asset never shows up as pickable footage.
    Image outputs of `asset_kind=character`/`scene` jobs are excluded — those
    stay on the character/scene library pickers (`GET /v1/generation-jobs`).
    """
    sheet_output = exists().where(
        GenerationJob.request_json["asset_kind"].astext.in_(_EDITOR_LIBRARY_HIDDEN_ASSET_KINDS),
        or_(
            GenerationJob.output_asset_id == Asset.id,
            GenerationJob.output_asset_ids_json.op("@>")(func.to_jsonb(Asset.id)),
            # Failed/partial jobs still write `generated/{job_id}/…` but may
            # never stamp `output_asset_id`.
            Asset.object_key.like(func.concat("generated/", GenerationJob.id, "/%")),
        ),
    )
    stmt = (
        select(Asset)
        .where(
            Asset.owner_user_id == user_id,
            Asset.role.in_([AssetRole.GENERATION_OUTPUT, AssetRole.EDITOR_SOURCE]),
            Asset.moderation_status != ModerationStatus.REJECTED,
            or_(Asset.media_type != MediaType.IMAGE, ~sheet_output),
        )
        .order_by(Asset.created_at.desc())
        .limit(limit)
    )
    if media_type is not None:
        stmt = stmt.where(Asset.media_type == media_type)
    return list(session.scalars(stmt))


def _source_version_output_id(session: Session, source_work_version_id: str | None) -> str | None:
    if not source_work_version_id:
        return None
    version = session.get(WorkVersion, source_work_version_id)
    return version.primary_output_asset_id if version else None


def licensed_remix_source_output_id(
    session: Session,
    *,
    user_id: str,
    source_work_version_id: str | None,
) -> str | None:
    """The source version's primary output, if this user may remix that work.

    Only that one asset is exempt from the usual owner check — a remixer
    still cannot attach an arbitrary foreign id. Call this at submit time;
    the worker reuses the already-resolved `source_work_version_id` without
    re-billing or re-asserting.
    """
    output_id = _source_version_output_id(session, source_work_version_id)
    if not output_id:
        return None
    version = session.get(WorkVersion, source_work_version_id)
    work = session.get(Work, version.work_id) if version else None
    if work is None:
        return None
    licensing.assert_remixable(work, user_id, session)
    return output_id


def attach_licensed_source_video(
    session: Session,
    *,
    params: dict[str, Any],
    source_work_version_id: str | None,
) -> None:
    """Prepend the remix source clip when the client omitted it.

    Image sources are left alone — `image_to_video` still needs a still the
    caller actually attached. Authorization is the caller's job
    (`jobs._resolve_source_version` already ran `assert_remixable`).
    """
    if not source_work_version_id:
        return
    version = session.get(WorkVersion, source_work_version_id)
    if version is None or not version.primary_output_asset_id:
        return
    asset = session.get(Asset, version.primary_output_asset_id)
    if asset is None or asset.media_type != MediaType.VIDEO:
        return
    refs = list(params.get("reference_asset_ids") or [])
    if version.primary_output_asset_id not in refs:
        params["reference_asset_ids"] = [version.primary_output_asset_id, *refs]


def _asset_is_usable_reference(
    asset: Asset | None,
    *,
    user_id: str,
    licensed_source_id: str | None,
    session: Session | None = None,
) -> bool:
    if asset is None:
        return False
    if asset.owner_user_id == user_id:
        return True
    if licensed_source_id and asset.id == licensed_source_id:
        return True
    if session is None:
        return False
    from app.domain.skill_library import service as skill_library_service

    return skill_library_service.asset_is_usable_skill_reference(
        session, asset=asset, viewer_id=user_id
    )


def validate_generation_references(
    session: Session,
    *,
    user_id: str,
    operation: str,
    params: dict[str, Any],
    source_work_version_id: str | None = None,
) -> None:
    """Validate ownership and media types before credits are reserved.

    Asset ids are user input.  Resolving them later in a worker without this
    ownership check would let a guessed private id become a signed provider
    URL, even though the object itself never becomes public. The exceptions
    are a remix-licensed source version's primary output, and a published
    marketplace skill's public cover (so an image-asset
    recipe can ride as an img2img reference without cloning the still).
    """

    ordinary_ids = list(params.get("reference_asset_ids") or [])
    video_options = params.get("video_options") or {}
    first_id = video_options.get("first_frame_asset_id")
    last_id = video_options.get("last_frame_asset_id")
    frame_ids = [asset_id for asset_id in (first_id, last_id) if asset_id]
    requested = ordinary_ids + frame_ids
    if len(set(requested)) != len(requested):
        raise ValidationFailed(
            "参考素材不能重复。", fields={"params.reference_asset_ids": "包含重复素材"}
        )
    if not requested:
        return

    licensed_source_id = licensed_remix_source_output_id(
        session, user_id=user_id, source_work_version_id=source_work_version_id
    )
    rows = list(session.scalars(select(Asset).where(Asset.id.in_(requested))))
    by_id = {asset.id: asset for asset in rows}
    for asset_id in requested:
        if not _asset_is_usable_reference(
            by_id.get(asset_id),
            user_id=user_id,
            licensed_source_id=licensed_source_id,
            session=session,
        ):
            raise ValidationFailed(
                "参考素材不存在或不属于当前用户。",
                fields={"params.reference_asset_ids": "包含不可用素材"},
            )

    for asset_id in frame_ids:
        if by_id[asset_id].media_type != MediaType.IMAGE:
            raise ValidationFailed(
                "首帧和尾帧必须是图片。",
                fields={"params.video_options": "首尾帧必须是图片"},
            )

    if operation == Operation.IMAGE_TO_IMAGE.value:
        if any(by_id[asset_id].media_type != MediaType.IMAGE for asset_id in ordinary_ids):
            raise ValidationFailed(
                "图生图参考素材必须是图片。",
                fields={"params.reference_asset_ids": "必须是图片"},
            )
    elif operation in {
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }:
        allowed = {MediaType.IMAGE, MediaType.VIDEO}
        if any(by_id[asset_id].media_type not in allowed for asset_id in ordinary_ids):
            raise ValidationFailed(
                "视频生成参考素材仅支持图片或视频。",
                fields={"params.reference_asset_ids": "仅支持图片或视频"},
            )
    elif operation == Operation.AUDIO_GENERATION.value:
        # The one reference `audio_generation` ever takes is a voice-clone
        # sample — count-capped to 1 in `validate_generation_params`
        # (`api/schemas/jobs.py`), media-type-checked here like every other
        # operation's references.
        if any(by_id[asset_id].media_type != MediaType.AUDIO for asset_id in ordinary_ids):
            raise ValidationFailed(
                "声音克隆参考素材必须是音频。",
                fields={"params.reference_asset_ids": "必须是音频"},
            )
    elif operation == Operation.MUSIC_GENERATION.value:
        # `api.schemas.jobs.validate_generation_params` already rejects any
        # reference for this operation before credits are reserved — this
        # is the belt-and-suspenders check for a caller that bypasses that
        # schema (or a future regression in it): no reference asset is ever
        # a legal `music_generation` input in v1, regardless of media type.
        raise ValidationFailed(
            "音乐/音效生成不支持参考素材。",
            fields={"params.reference_asset_ids": "暂不支持参考素材"},
        )
    elif operation == Operation.VIDEO_ANALYSIS.value:
        if any(by_id[asset_id].media_type != MediaType.VIDEO for asset_id in ordinary_ids):
            raise ValidationFailed(
                "视频解析的参考素材必须是视频。",
                fields={"params.reference_asset_ids": "必须是视频"},
            )
        if any(
            (by_id[asset_id].duration_ms or 0) > VIDEO_ANALYSIS_MAX_DURATION_MS
            for asset_id in ordinary_ids
        ):
            raise ValidationFailed(
                "视频解析的参考视频时长不能超过 3 分钟。",
                fields={"params.reference_asset_ids": "时长超过 3 分钟"},
            )


def provider_references_for(
    session: Session,
    *,
    user_id: str,
    asset_ids: Sequence[str],
    video_options: dict[str, Any] | None = None,
    source_work_version_id: str | None = None,
) -> list[ProviderReference]:
    """Resolve validated user assets into provider-neutral reference inputs."""

    options = video_options or {}
    frame_pairs = [
        (options.get("first_frame_asset_id"), "first_frame"),
        (options.get("last_frame_asset_id"), "last_frame"),
    ]
    ordered: list[tuple[str, str | None]] = [(asset_id, None) for asset_id in asset_ids]
    ordered.extend((asset_id, frame_type) for asset_id, frame_type in frame_pairs if asset_id)
    if not ordered:
        return []

    licensed_source_id = _source_version_output_id(session, source_work_version_id)
    ids = [asset_id for asset_id, _ in ordered]
    rows = session.scalars(select(Asset).where(Asset.id.in_(ids)))
    by_id = {
        asset.id: asset
        for asset in rows
        if _asset_is_usable_reference(
            asset,
            user_id=user_id,
            licensed_source_id=licensed_source_id,
            session=session,
        )
    }
    return [
        ProviderReference(
            object_key=by_id[asset_id].object_key,
            media_type=by_id[asset_id].media_type,
            frame_type=frame_type,
        )
        for asset_id, frame_type in ordered
        if asset_id in by_id
    ]


def _extract_frame_bytes(payload: bytes, *, position: str) -> bytes:
    """Shells out to `ffmpeg` for exactly one decoded frame.

    Reads/writes through stdin/stdout (same shape as `analysis.probe_bytes`'s
    `ffprobe` call) so there is no temp file to clean up. `last` runs the
    decoded stream through the `reverse` filter (buffers every frame, then
    emits them back-to-front) and takes *that* stream's first frame, rather
    than seeking to `duration_ms - epsilon` — seeking landed exactly on (or
    past) the container's real last decodable timestamp often enough to come
    back empty, since a stored `Asset.duration_ms` is not guaranteed to be
    frame-exact. `reverse` is exact regardless, and fine memory-wise for the
    single-digit-second clips this is ever called against. Both paths force
    `yuvj420p` — an mjpeg encode of a non-full-range source (fine for
    picture, common for a generated clip) otherwise refuses to open the
    encoder at all.
    """
    if shutil.which("ffmpeg") is None:
        raise ValidationFailed("服务器未安装 ffmpeg，无法截取视频画面。")
    args = ["ffmpeg", "-v", "error", "-y", "-i", "pipe:0"]
    if position == "last":
        args += ["-vf", "reverse"]
    args += ["-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "pipe:1"]
    proc = subprocess.run(args, input=payload, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        raise ValidationFailed("无法截取该视频的画面帧。")
    return proc.stdout


def extract_video_frame(session: Session, *, user_id: str, asset_id: str, position: str) -> Asset:
    """Grabs a single frame from an already-generated video and registers it
    as a new, private image `Asset` (`role=GENERATION_REFERENCE`) — lets a
    caller feed it straight back in as `first_frame_asset_id`/
    `last_frame_asset_id` on the next `image_to_video` submission. This is
    what powers the script studio's "衔接上一镜头" continuity feature: the
    previous script breakpoint's video's last frame becomes the next one's
    first frame, without the user having to download/re-upload anything.

    Not routed through the upload handshake (`presign`/`complete_upload`) —
    the platform derived these bytes from the caller's own asset, so there is
    no client-declared checksum/size to verify against. Moderation still
    defaults to `PENDING`, same as any other reference asset; this is a
    private, generation-input asset, never shown publicly on its own.
    """
    if position not in ("first", "last"):
        raise ValidationFailed("不支持的截帧位置。", fields={"position": "只能是 first 或 last"})
    source = session.get(Asset, asset_id)
    if source is None or source.owner_user_id != user_id:
        # 404, not 403 — same anti-probing stance as `get_asset`.
        raise NotFound("素材不存在。")
    if source.media_type != MediaType.VIDEO:
        raise ValidationFailed("只能对视频素材截取画面帧。")

    payload = s3.get_object(source.object_key)
    frame_bytes = _extract_frame_bytes(payload, position=position)
    width, height, _ = _probe(frame_bytes, "image/jpeg")

    object_key = f"derived/frames/{user_id}/{new_id('obj')}.jpg"
    s3.put_object(object_key, frame_bytes, content_type="image/jpeg")

    frame_asset = Asset(
        owner_user_id=user_id,
        object_key=object_key,
        media_type=MediaType.IMAGE,
        mime_type="image/jpeg",
        size_bytes=len(frame_bytes),
        checksum_sha256=hashlib.sha256(frame_bytes).hexdigest(),
        role=AssetRole.GENERATION_REFERENCE,
        width=width,
        height=height,
        moderation_status=ModerationStatus.PENDING,
        visibility=Visibility.PRIVATE,
        # A frame of a real person still shows that person. It inherits the
        # flag but not the consent — see `app.domain.consent.service`.
        depicts_real_person=source.depicts_real_person,
    )
    session.add(frame_asset)
    session.flush()
    return frame_asset


def register_generated_asset(
    session: Session,
    *,
    owner_user_id: str,
    object_key: str,
    mime_type: str,
    width: int | None,
    height: int | None,
    duration_ms: int | None,
    is_prototype: bool = True,
    generation_job_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> Asset:
    """Registers provider output, which bypasses the upload handshake because
    the platform itself produced the bytes."""
    payload = s3.get_object(object_key)
    asset = Asset(
        owner_user_id=owner_user_id,
        object_key=object_key,
        media_type=_media_type_for(mime_type),
        mime_type=mime_type,
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=AssetRole.GENERATION_OUTPUT,
        width=width,
        height=height,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.PENDING,
        visibility=Visibility.PRIVATE,
        is_prototype=is_prototype,
    )
    session.add(asset)
    session.flush()

    if asset.media_type == MediaType.IMAGE:
        record_fingerprint(session, asset=asset, payload=payload)
    record_provenance(
        session,
        asset=asset,
        generation_job_id=generation_job_id,
        details=provenance or {},
    )
    return asset


def record_provenance(
    session: Session,
    *,
    asset: Asset,
    generation_job_id: str | None,
    details: dict[str, Any],
) -> ProvenanceManifest:
    """Attaches the AI disclosure claim to a generated asset.

    The claim follows the shape of a C2PA assertion set so that turning on a
    real signer later is a matter of filling in `signature`, not reshaping the
    stored data.
    """
    claim = {
        "claim_generator": "zaolang",
        "format": asset.mime_type,
        "instance_id": asset.id,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": (
                                "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
                            ),
                            "when": utcnow().isoformat(),
                        }
                    ]
                },
            },
            {
                "label": "c2pa.hash.data",
                "data": {"alg": "sha256", "hash": asset.checksum_sha256},
            },
        ],
        **details,
    }

    manifest = ProvenanceManifest(
        asset_id=asset.id,
        generation_job_id=generation_job_id,
        claim_json=claim,
        # Stays null until a signing identity is configured; an unsigned claim
        # is honest about being unverifiable.
        signature=None,
    )
    session.add(manifest)
    session.flush()
    return manifest


def provenance_for(session: Session, asset_id: str) -> ProvenanceManifest | None:
    return session.scalar(select(ProvenanceManifest).where(ProvenanceManifest.asset_id == asset_id))


def record_fingerprint(
    session: Session, *, asset: Asset, payload: bytes
) -> ContentFingerprint | None:
    """Stores a perceptual hash for duplicate and laundering detection."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            phash = imagehash.phash(image.convert("RGB"))
    except (UnidentifiedImageError, OSError):
        logger.warning("could not fingerprint asset %s", asset.id)
        return None

    hex_value = str(phash)
    fingerprint = ContentFingerprint(
        asset_id=asset.id,
        algorithm="phash",
        fingerprint_hex=hex_value,
        fingerprint_bits=_to_signed_64(int(hex_value, 16)),
        frame_index=0,
    )
    session.add(fingerprint)
    session.flush()
    return fingerprint


def _to_signed_64(value: int) -> int:
    """Maps a 64-bit hash onto Postgres' signed bigint range."""
    masked = value & 0xFFFF_FFFF_FFFF_FFFF
    return masked - (1 << 64) if masked >= (1 << 63) else masked


def hamming_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def find_near_duplicates(
    session: Session, *, fingerprint_hex: str, exclude_asset_id: str | None = None, limit: int = 20
) -> list[tuple[Asset, int]]:
    """Finds visually similar assets.

    Compared in Python rather than SQL: pHash similarity is a bit-distance, not
    an ordering, so an index cannot answer it directly. The candidate set stays
    small because it is only ever run from the ops console.
    """
    rows = session.scalars(
        select(ContentFingerprint).where(ContentFingerprint.algorithm == "phash")
    )
    matches: list[tuple[Asset, int]] = []
    for row in rows:
        if exclude_asset_id and row.asset_id == exclude_asset_id:
            continue
        distance = hamming_distance(fingerprint_hex, row.fingerprint_hex)
        if distance <= DUPLICATE_HAMMING_THRESHOLD:
            asset = session.get(Asset, row.asset_id)
            if asset is not None:
                matches.append((asset, distance))
    matches.sort(key=lambda pair: pair[1])
    return matches[:limit]


def download_filename_for(asset: Asset) -> str:
    """ASCII-safe attachment name: `{asset.id}` plus the MIME's known suffix.

    Asset ids are typed prefixes (`ast_…`), so they are safe to interpolate
    into `Content-Disposition: filename="…"`. An unknown MIME keeps the bare
    id rather than inventing an extension.
    """
    ext = s3.ALLOWED_UPLOAD_MIME_TYPES.get(asset.mime_type, "")
    return f"{asset.id}{ext}"


def signed_url_for(
    session: Session,
    *,
    asset_id: str,
    viewer_user_id: str | None,
    viewer_is_staff: bool = False,
    download_name: str | None = None,
) -> str:
    """Mints a short-lived URL after an access check.

    Generation output and consent evidence stay owner-only until the work that
    contains them is published. Pass `download_name` to force
    `Content-Disposition: attachment` so a browser saves the object instead
    of playing it inline — playback URLs must omit it.
    """
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在。")

    is_owner = asset.owner_user_id == viewer_user_id
    if not (is_owner or viewer_is_staff or asset.visibility != Visibility.PRIVATE):
        raise NotFound("素材不存在。")

    settings = get_settings()
    return s3.presign_get(
        asset.object_key,
        expires_in=settings.download_url_ttl_seconds,
        download_name=download_name,
    )


def publish_asset(session: Session, asset: Asset) -> None:
    """Makes an asset readable by anyone who can see its work."""
    asset.visibility = Visibility.PUBLIC_VIEW_ONLY
    session.flush()


def delete_exclusive_assets(
    session: Session, *, asset_ids: Sequence[str], except_work_id: str
) -> list[str]:
    """Deletes objects that no other work, draft or profile still displays.

    Shared files stay: a descendant that reused the cover must keep resolving
    it. Fingerprints and provenance cascade with the asset row.
    """
    deleted: list[str] = []
    for asset_id in {item for item in asset_ids if item}:
        if _is_shared(session, asset_id, except_work_id):
            continue
        if _delete_asset(session, asset_id):
            deleted.append(asset_id)
    return deleted


def _is_shared(session: Session, asset_id: str, except_work_id: str) -> bool:
    other_version = session.scalar(
        select(WorkVersion.id)
        .where(
            WorkVersion.work_id != except_work_id,
            or_(
                WorkVersion.cover_asset_id == asset_id,
                WorkVersion.primary_output_asset_id == asset_id,
            ),
        )
        .limit(1)
    )
    if other_version is not None:
        return True

    other_draft = session.scalar(
        select(Draft.id)
        .where(
            Draft.output_asset_id == asset_id,
            or_(Draft.published_work_id.is_(None), Draft.published_work_id != except_work_id),
        )
        .limit(1)
    )
    if other_draft is not None:
        return True

    profile = session.scalar(
        select(Profile.user_id)
        .where(or_(Profile.avatar_asset_id == asset_id, Profile.cover_asset_id == asset_id))
        .limit(1)
    )
    if profile is not None:
        return True

    series_logo = session.scalar(select(Series.id).where(Series.logo_asset_id == asset_id).limit(1))
    if series_logo is not None:
        return True

    episode_preview = session.scalar(
        select(DramaEpisode.id).where(DramaEpisode.preview_asset_id == asset_id).limit(1)
    )
    if episode_preview is not None:
        return True

    for reused in session.scalars(select(LineageEdge.reused_asset_ids_json)):
        if asset_id in (reused or []):
            return True
    return False


def _delete_asset(session: Session, asset_id: str) -> bool:
    asset = session.get(Asset, asset_id)
    if asset is None:
        return False
    try:
        s3.delete_object(asset.object_key)
    except ClientError:
        logger.warning("object %s already gone while purging asset %s", asset.object_key, asset_id)
    session.delete(asset)
    session.flush()
    return True


def _probe(payload: bytes, mime_type: str) -> tuple[int | None, int | None, MediaType]:
    media_type = _media_type_for(mime_type)
    if media_type != MediaType.IMAGE:
        return None, None, media_type
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height, MediaType.IMAGE
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationFailed("无法解析该图片文件。") from exc


def _media_type_for(mime_type: str) -> MediaType:
    if mime_type.startswith("video/"):
        return MediaType.VIDEO
    if mime_type.startswith("audio/"):
        return MediaType.AUDIO
    return MediaType.IMAGE
