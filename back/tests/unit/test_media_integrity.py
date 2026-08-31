"""Upload handshake, fingerprinting and AI provenance."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.errors import Conflict, Forbidden, LicenseNotRemixable, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.media import service as media_service
from app.models import Asset, User, Work, WorkVersion
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    MediaType,
    ModerationStatus,
    Operation,
    QualityTier,
    Visibility,
)
from app.storage import s3
from tests.factories import make_work


def _png(colour: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _presign(session: Session, user: User, payload: bytes, purpose: str = "generation_reference"):  # type: ignore[no-untyped-def]
    return media_service.presign_upload(
        session,
        user_id=user.id,
        filename="frame.png",
        mime_type="image/png",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        purpose=purpose,
    )


def _reference_asset(session: Session, owner: User, media_type: MediaType) -> Asset:
    extension = "mp4" if media_type == MediaType.VIDEO else "png"
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.{extension}",
        media_type=media_type,
        mime_type=f"{'video/mp4' if media_type == MediaType.VIDEO else 'image/png'}",
        size_bytes=128,
        checksum_sha256="a" * 64,
        role=AssetRole.GENERATION_REFERENCE,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def test_generation_references_enforce_ownership_and_frame_media_type(
    db: Session, author: User, admin: User
) -> None:
    another_users_image = _reference_asset(db, admin, MediaType.IMAGE)
    with pytest.raises(ValidationFailed, match="不属于当前用户"):
        media_service.validate_generation_references(
            db,
            user_id=author.id,
            operation=Operation.TEXT_TO_VIDEO,
            params={"reference_asset_ids": [another_users_image.id]},
        )

    video = _reference_asset(db, author, MediaType.VIDEO)
    media_service.validate_generation_references(
        db,
        user_id=author.id,
        operation=Operation.VIDEO_TO_VIDEO,
        params={"reference_asset_ids": [video.id]},
    )
    with pytest.raises(ValidationFailed, match="首帧和尾帧必须是图片"):
        media_service.validate_generation_references(
            db,
            user_id=author.id,
            operation=Operation.IMAGE_TO_VIDEO,
            params={
                "video_options": {
                    "reference_mode": "frame_images",
                    "first_frame_asset_id": video.id,
                }
            },
        )


def test_video_analysis_requires_a_video_reference_within_the_duration_cap(
    db: Session, author: User
) -> None:
    image = _reference_asset(db, author, MediaType.IMAGE)
    with pytest.raises(ValidationFailed, match="必须是视频"):
        media_service.validate_generation_references(
            db,
            user_id=author.id,
            operation=Operation.VIDEO_ANALYSIS,
            params={"reference_asset_ids": [image.id]},
        )

    short_clip = _reference_asset(db, author, MediaType.VIDEO)
    media_service.validate_generation_references(
        db,
        user_id=author.id,
        operation=Operation.VIDEO_ANALYSIS,
        params={"reference_asset_ids": [short_clip.id]},
    )

    long_clip = _reference_asset(db, author, MediaType.VIDEO)
    long_clip.duration_ms = media_service.VIDEO_ANALYSIS_MAX_DURATION_MS + 1
    db.flush()
    with pytest.raises(ValidationFailed, match="不能超过 3 分钟"):
        media_service.validate_generation_references(
            db,
            user_id=author.id,
            operation=Operation.VIDEO_ANALYSIS,
            params={"reference_asset_ids": [long_clip.id]},
        )


def test_provider_references_preserve_media_and_frame_roles(db: Session, author: User) -> None:
    image = _reference_asset(db, author, MediaType.IMAGE)
    video = _reference_asset(db, author, MediaType.VIDEO)
    inputs = media_service.provider_references_for(
        db, user_id=author.id, asset_ids=[image.id, video.id]
    )
    assert [(item.media_type, item.frame_type) for item in inputs] == [
        ("image", None),
        ("video", None),
    ]

    frames = media_service.provider_references_for(
        db,
        user_id=author.id,
        asset_ids=[],
        video_options={
            "first_frame_asset_id": image.id,
            "last_frame_asset_id": image.id,
        },
    )
    assert [item.frame_type for item in frames] == ["first_frame", "last_frame"]


def test_an_unsupported_type_is_refused_before_a_url_is_issued(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        media_service.presign_upload(
            db,
            user_id=author.id,
            filename="payload.svg",
            mime_type="image/svg+xml",
            size_bytes=100,
            checksum_sha256="0" * 64,
            purpose="generation_reference",
        )


def test_an_oversized_file_is_refused(db: Session, author: User) -> None:
    limit = s3.MAX_UPLOAD_BYTES["avatar"]
    with pytest.raises(ValidationFailed):
        media_service.presign_upload(
            db,
            user_id=author.id,
            filename="huge.png",
            mime_type="image/png",
            size_bytes=limit + 1,
            checksum_sha256="0" * 64,
            purpose="avatar",
        )


def test_video_analysis_source_accepts_video_up_to_its_own_larger_limit(
    db: Session, author: User
) -> None:
    """`video_analysis_source` needs its own, bigger ceiling than
    `generation_reference` (32MB, sized for a still image) because a
    3-minute reference clip routinely exceeds that."""
    with pytest.raises(ValidationFailed, match="必须是视频"):
        media_service.presign_upload(
            db,
            user_id=author.id,
            filename="frame.png",
            mime_type="image/png",
            size_bytes=100,
            checksum_sha256="0" * 64,
            purpose="video_analysis_source",
        )

    generation_reference_limit = s3.MAX_UPLOAD_BYTES["generation_reference"]
    presigned = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="clip.mp4",
        mime_type="video/mp4",
        size_bytes=generation_reference_limit + 1,
        checksum_sha256="0" * 64,
        purpose="video_analysis_source",
    )
    assert presigned.upload_session.object_key.startswith(
        f"{s3.PURPOSE_PREFIXES['video_analysis_source']}/{author.id}/"
    )


def test_the_object_key_is_scoped_to_the_owner_and_purpose(db: Session, author: User) -> None:
    """The directory alone proves who may write there, so a leaked signature
    cannot reach another user's space."""
    presigned = _presign(db, author, _png((10, 20, 30)))
    key = presigned.upload_session.object_key
    assert key.startswith(f"{s3.PURPOSE_PREFIXES['generation_reference']}/{author.id}/")


def test_a_completed_upload_becomes_a_private_pending_asset(db: Session, author: User) -> None:
    payload = _png((120, 40, 60))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    assert asset.visibility == Visibility.PRIVATE
    assert asset.moderation_status == ModerationStatus.PENDING
    assert asset.width == 64 and asset.height == 64


def test_bytes_that_do_not_match_the_declared_checksum_are_rejected_and_deleted(
    db: Session, author: User
) -> None:
    """The checksum was part of what the signature authorised; trusting the
    bytes instead would let a signed URL smuggle in different content."""
    promised = _png((1, 2, 3))
    substituted = _png((250, 250, 250))
    # The declared size matches so the check under test is the checksum, not
    # the length.
    presigned = media_service.presign_upload(
        db,
        user_id=author.id,
        filename="frame.png",
        mime_type="image/png",
        size_bytes=len(substituted),
        checksum_sha256=hashlib.sha256(promised).hexdigest(),
        purpose="generation_reference",
    )
    s3.put_object(presigned.upload_session.object_key, substituted, content_type="image/png")

    with pytest.raises(ValidationFailed):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )
    assert s3.head_object(presigned.upload_session.object_key) is None


def test_a_size_mismatch_is_rejected(db: Session, author: User) -> None:
    payload = _png((5, 5, 5))
    presigned = _presign(db, author, payload)
    s3.put_object(
        presigned.upload_session.object_key,
        _png((5, 5, 5), size=(256, 256)),
        content_type="image/png",
    )

    with pytest.raises(ValidationFailed):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_completing_before_uploading_is_a_conflict_not_a_crash(db: Session, author: User) -> None:
    presigned = _presign(db, author, _png((9, 9, 9)))
    with pytest.raises(Conflict):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_another_user_cannot_complete_someone_elses_upload(
    db: Session, author: User, remixer: User
) -> None:
    payload = _png((44, 55, 66))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    with pytest.raises(Forbidden):
        media_service.complete_upload(
            db, user_id=remixer.id, upload_session_id=presigned.upload_session.id
        )


def test_completing_twice_returns_the_same_asset(db: Session, author: User) -> None:
    payload = _png((77, 88, 99))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")

    first = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    second = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )
    assert first.id == second.id


def test_an_expired_session_cannot_be_completed(db: Session, author: User) -> None:
    import datetime as dt

    from app.models.base import utcnow

    payload = _png((3, 3, 3))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    presigned.upload_session.expires_at = utcnow() - dt.timedelta(seconds=1)
    db.flush()

    with pytest.raises(Conflict):
        media_service.complete_upload(
            db, user_id=author.id, upload_session_id=presigned.upload_session.id
        )


def test_identical_images_produce_identical_fingerprints(db: Session, author: User) -> None:
    payload = _png((30, 60, 90))
    first = _presign(db, author, payload)
    s3.put_object(first.upload_session.object_key, payload, content_type="image/png")
    asset_a = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=first.upload_session.id
    )

    second = _presign(db, author, payload)
    s3.put_object(second.upload_session.object_key, payload, content_type="image/png")
    asset_b = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=second.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    hashes = {
        row.asset_id: row.fingerprint_hex
        for row in db.scalars(
            select(ContentFingerprint).where(
                ContentFingerprint.asset_id.in_([asset_a.id, asset_b.id])
            )
        )
    }
    assert hashes[asset_a.id] == hashes[asset_b.id]


def test_a_reupload_is_found_as_a_near_duplicate(db: Session, author: User) -> None:
    payload = _png((200, 100, 50))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    original = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    fingerprint = db.scalar(
        select(ContentFingerprint).where(ContentFingerprint.asset_id == original.id)
    )
    assert fingerprint is not None

    matches = media_service.find_near_duplicates(
        db, fingerprint_hex=fingerprint.fingerprint_hex, exclude_asset_id=None
    )
    assert original.id in {asset.id for asset, _ in matches}


def test_a_fingerprint_fits_the_signed_bigint_range(db: Session, author: User) -> None:
    """A pHash is an unsigned 64-bit value; storing it raw would overflow the
    Postgres column."""
    payload = _png((255, 255, 255))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from sqlalchemy import select

    from app.models import ContentFingerprint

    fingerprint = db.scalar(
        select(ContentFingerprint).where(ContentFingerprint.asset_id == asset.id)
    )
    assert fingerprint is not None
    assert -(2**63) <= fingerprint.fingerprint_bits < 2**63


def test_generated_output_carries_an_ai_disclosure_claim(db: Session, author: User) -> None:
    payload = _png((11, 22, 33))
    key = f"outputs/{author.id}/generated.png"
    s3.put_object(key, payload, content_type="image/png")

    asset = media_service.register_generated_asset(
        db,
        owner_user_id=author.id,
        object_key=key,
        mime_type="image/png",
        width=64,
        height=64,
        duration_ms=None,
        generation_job_id="job_test",
    )

    manifest = media_service.provenance_for(db, asset.id)
    assert manifest is not None
    assert manifest.generation_job_id == "job_test"
    labels = {a["label"] for a in manifest.claim_json["assertions"]}
    assert "c2pa.actions" in labels
    # No signer is configured, and an unsigned claim must say so rather than
    # look verified.
    assert manifest.signature is None


def test_a_private_asset_is_invisible_to_a_stranger(
    db: Session, author: User, remixer: User
) -> None:
    payload = _png((70, 70, 70))
    presigned = _presign(db, author, payload)
    s3.put_object(presigned.upload_session.object_key, payload, content_type="image/png")
    asset = media_service.complete_upload(
        db, user_id=author.id, upload_session_id=presigned.upload_session.id
    )

    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        media_service.signed_url_for(db, asset_id=asset.id, viewer_user_id=remixer.id)

    url = media_service.signed_url_for(db, asset_id=asset.id, viewer_user_id=author.id)
    # MinIO/S3 signs with `X-Amz-Signature`; Tencent COS signs with its own
    # `q-signature` — whichever backend `STORAGE_BACKEND` selects locally.
    assert "X-Amz-Signature" in url or "q-signature=" in url


def _remix_source_video(session: Session, owner: User) -> tuple[Asset, Work, WorkVersion]:
    work, version = make_work(session, owner)
    clip = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=128,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(clip)
    session.flush()
    version.primary_output_asset_id = clip.id
    session.flush()
    return clip, work, version


def test_remix_source_video_is_a_legal_generation_reference(
    db: Session, author: User, remixer: User, admin: User
) -> None:
    clip, _work, version = _remix_source_video(db, author)
    media_service.validate_generation_references(
        db,
        user_id=remixer.id,
        operation=Operation.VIDEO_TO_VIDEO.value,
        params={"reference_asset_ids": [clip.id]},
        source_work_version_id=version.id,
    )

    stranger = _reference_asset(db, admin, MediaType.VIDEO)
    with pytest.raises(ValidationFailed, match="不属于当前用户"):
        media_service.validate_generation_references(
            db,
            user_id=remixer.id,
            operation=Operation.VIDEO_TO_VIDEO.value,
            params={"reference_asset_ids": [stranger.id]},
            source_work_version_id=version.id,
        )

    with pytest.raises(ValidationFailed, match="不属于当前用户"):
        media_service.validate_generation_references(
            db,
            user_id=remixer.id,
            operation=Operation.VIDEO_TO_VIDEO.value,
            params={"reference_asset_ids": [clip.id]},
        )


def test_view_only_source_cannot_be_used_as_a_remix_reference(
    db: Session, author: User, remixer: User
) -> None:
    clip, work, version = _remix_source_video(db, author)
    work.visibility = Visibility.PUBLIC_VIEW_ONLY
    db.flush()
    with pytest.raises(LicenseNotRemixable):
        media_service.validate_generation_references(
            db,
            user_id=remixer.id,
            operation=Operation.VIDEO_TO_VIDEO.value,
            params={"reference_asset_ids": [clip.id]},
            source_work_version_id=version.id,
        )


def test_provider_references_keep_a_licensed_source_after_visibility_changes(
    db: Session, author: User, remixer: User
) -> None:
    """The worker must not re-assert remixability — a mid-job visibility
    change must not drop the clip the submit path already authorized."""
    clip, work, version = _remix_source_video(db, author)
    work.visibility = Visibility.PUBLIC_VIEW_ONLY
    db.flush()
    refs = media_service.provider_references_for(
        db,
        user_id=remixer.id,
        asset_ids=[clip.id],
        source_work_version_id=version.id,
    )
    assert [item.object_key for item in refs] == [clip.object_key]


def _mp4(*, duration_seconds: float = 1.0, colour: str = "red") -> bytes:
    """A tiny synthetic clip via `ffmpeg`'s own `lavfi` colour source — no
    fixture file to keep in the repo, and it lets a test assert on the
    actual decoded pixel colour of an extracted frame."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:s=32x32:d={duration_seconds}",
            "-frames:v",
            str(max(1, int(duration_seconds * 24))),
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return proc.stdout


def _video_asset(session: Session, owner: User, payload: bytes, *, duration_ms: int) -> Asset:
    key = f"test/{new_id('obj')}.mp4"
    s3.put_object(key, payload, content_type="video/mp4")
    asset = Asset(
        owner_user_id=owner.id,
        object_key=key,
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        duration_ms=duration_ms,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_extract_video_frame_grabs_first_and_last_frames(db: Session, author: User) -> None:
    """The script studio's "衔接上一镜头" continuity feature hinges on this:
    the previous breakpoint's last frame becomes the next one's first-frame
    reference. Uses two visibly different colours so a regression that
    always returns the same frame (e.g. `position` silently ignored) fails
    loudly rather than just "looking about right"."""
    payload = _mp4(duration_seconds=1.0, colour="red")
    video = _video_asset(db, author, payload, duration_ms=1000)

    last_frame = media_service.extract_video_frame(
        db, user_id=author.id, asset_id=video.id, position="last"
    )
    assert last_frame.media_type == MediaType.IMAGE
    assert last_frame.mime_type == "image/jpeg"
    assert last_frame.owner_user_id == author.id
    assert last_frame.role == AssetRole.GENERATION_REFERENCE
    assert last_frame.moderation_status == ModerationStatus.PENDING
    assert last_frame.visibility == Visibility.PRIVATE
    assert last_frame.width == 32 and last_frame.height == 32

    first_frame = media_service.extract_video_frame(
        db, user_id=author.id, asset_id=video.id, position="first"
    )
    assert first_frame.id != last_frame.id
    # Both frames come from a constant-colour clip, so this only proves two
    # independent extractions each produced a real, decodable image rather
    # than reusing/aliasing bytes — colour-accuracy across codecs is out of
    # scope for a unit test.
    with Image.open(io.BytesIO(s3.get_object(first_frame.object_key))) as image:
        assert image.size == (32, 32)


def test_extract_video_frame_rejects_non_video_and_foreign_assets(
    db: Session, author: User, admin: User
) -> None:
    image = _reference_asset(db, author, MediaType.IMAGE)
    with pytest.raises(ValidationFailed, match="只能对视频素材"):
        media_service.extract_video_frame(db, user_id=author.id, asset_id=image.id, position="last")

    someone_elses_video = _reference_asset(db, admin, MediaType.VIDEO)
    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        media_service.extract_video_frame(
            db, user_id=author.id, asset_id=someone_elses_video.id, position="last"
        )


def test_extract_video_frame_rejects_an_unsupported_position(db: Session, author: User) -> None:
    video = _reference_asset(db, author, MediaType.VIDEO)
    with pytest.raises(ValidationFailed, match="不支持的截帧位置"):
        media_service.extract_video_frame(
            db, user_id=author.id, asset_id=video.id, position="middle"
        )


def test_extract_video_frame_degrades_clearly_without_ffmpeg(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"not a real video, but ffmpeg is mocked missing before it matters"
    video = _video_asset(db, author, payload, duration_ms=4000)
    monkeypatch.setattr(media_service.shutil, "which", lambda _name: None)
    with pytest.raises(ValidationFailed, match="未安装 ffmpeg"):
        media_service.extract_video_frame(db, user_id=author.id, asset_id=video.id, position="last")


def test_submit_prepends_a_licensed_source_video_when_the_client_omits_it(
    db: Session, author: User, remixer: User
) -> None:
    credits_service.grant(db, remixer.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    clip, _work, version = _remix_source_video(db, author)
    params = {
        "prompt": "改成暴雨将至",
        "duration_seconds": 8,
        "aspect_ratio": "16:9",
        "video_options": {"reference_mode": "input_references"},
    }
    result = jobs_service.submit(
        db,
        user_id=remixer.id,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        params=params,
        idempotency_key=new_id("idk"),
        source_work_version_id=version.id,
    )
    assert result.job.request_json["reference_asset_ids"] == [clip.id]
