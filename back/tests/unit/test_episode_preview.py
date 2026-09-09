"""Roster thumbnail auto-fill: empty-only write, explicit overwrite, job settle."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.editor import service as editor_service
from app.domain.errors import ValidationFailed
from app.domain.media import service as media_service
from app.domain.publishing import service as publishing
from app.models import Asset, DramaEpisode, Series, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from app.workflows.nodes import _maybe_fill_linked_episode_preview


def _image(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.jpg",
        media_type=MediaType.IMAGE,
        mime_type="image/jpeg",
        size_bytes=64,
        checksum_sha256="a" * 64,
        role=AssetRole.COVER,
        width=1080,
        height=1920,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _video(session: Session, owner: User) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=2048,
        checksum_sha256="b" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1080,
        height=1920,
        duration_ms=8_000,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def _episode_with_linked_video(session: Session, owner: User) -> tuple[DramaEpisode, Asset]:
    series = Series(owner_user_id=owner.id, title="预览挂钩", kind="drama")
    session.add(series)
    session.flush()
    episode = DramaEpisode(series_id=series.id, episode_number=1, title="第一集")
    session.add(episode)
    session.flush()
    video = _video(session, owner)
    draft = publishing.create_draft(
        session,
        user_id=owner.id,
        source_work_id=None,
        params={"prompt": "成片", "link_episode_id": episode.id},
    )
    draft.output_asset_id = video.id
    session.flush()
    editor_service.create_content_link(
        session,
        user_id=owner.id,
        episode_id=episode.id,
        content_type="draft",
        content_ref_id=draft.id,
    )
    return episode, video


def _stub_extract(monkeypatch: pytest.MonkeyPatch) -> list[Asset]:
    frames: list[Asset] = []

    def fake_extract(session: Session, *, user_id: str, asset_id: str, position: str) -> Asset:
        source = session.get(Asset, asset_id)
        assert source is not None
        assert source.owner_user_id == user_id
        assert position == "first"
        frame = Asset(
            owner_user_id=user_id,
            object_key=f"derived/frames/{user_id}/{new_id('obj')}.jpg",
            media_type=MediaType.IMAGE,
            mime_type="image/jpeg",
            size_bytes=64,
            checksum_sha256="c" * 64,
            role=AssetRole.GENERATION_REFERENCE,
            width=1080,
            height=1920,
            moderation_status=ModerationStatus.PENDING,
            visibility=Visibility.PRIVATE,
        )
        session.add(frame)
        session.flush()
        frames.append(frame)
        return frame

    monkeypatch.setattr(media_service, "extract_video_frame", fake_extract)
    return frames


def test_maybe_fill_writes_once_and_explicit_overwrite_replaces(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = _stub_extract(monkeypatch)
    episode, _video = _episode_with_linked_video(db, author)
    # create_content_link auto-fills the empty preview.
    assert episode.preview_asset_id == frames[0].id

    editor_service.maybe_fill_episode_preview(db, episode=episode, actor_user_id=author.id)
    assert episode.preview_asset_id == frames[0].id
    assert len(frames) == 1

    editor_service.maybe_fill_episode_preview(
        db, episode=episode, actor_user_id=author.id, overwrite=True
    )
    assert episode.preview_asset_id == frames[1].id


def test_maybe_fill_overwrite_without_video_raises(db: Session, author: User) -> None:
    series = Series(owner_user_id=author.id, title="空集", kind="drama")
    db.add(series)
    db.flush()
    episode = DramaEpisode(series_id=series.id, episode_number=1, title="第一集")
    db.add(episode)
    db.flush()
    with pytest.raises(ValidationFailed, match="暂无可用视频"):
        editor_service.maybe_fill_episode_preview(
            db, episode=episode, actor_user_id=author.id, overwrite=True
        )


def test_settle_hook_fills_preview_for_linked_video_job(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = _stub_extract(monkeypatch)
    series = Series(owner_user_id=author.id, title="结算挂钩", kind="drama")
    db.add(series)
    db.flush()
    episode = DramaEpisode(series_id=series.id, episode_number=1, title="第一集")
    db.add(episode)
    db.flush()
    video = _video(db, author)
    draft = publishing.create_draft(
        db,
        user_id=author.id,
        source_work_id=None,
        params={"prompt": "成片", "link_episode_id": episode.id},
    )
    draft.output_asset_id = video.id
    db.flush()

    _maybe_fill_linked_episode_preview(db, draft)
    assert episode.preview_asset_id == frames[0].id

    uploaded = _image(db, author)
    episode.preview_asset_id = uploaded.id
    db.flush()
    _maybe_fill_linked_episode_preview(db, draft)
    assert episode.preview_asset_id == uploaded.id


def test_settle_hook_skips_draft_without_link_episode_id(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = _stub_extract(monkeypatch)
    draft = publishing.create_draft(
        db, user_id=author.id, source_work_id=None, params={"prompt": "独立成片"}
    )
    draft.output_asset_id = _video(db, author).id
    db.flush()
    _maybe_fill_linked_episode_preview(db, draft)
    assert frames == []
