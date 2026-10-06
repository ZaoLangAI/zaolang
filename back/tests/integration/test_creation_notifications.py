"""Creation notifications upsert with the job / export they track."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.editor import exports as export_service
from app.domain.editor import state_machine as editor_sm
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.notifications import push as notification_push
from app.models import DeliveryVariant, Notification, User
from app.models.base import new_id
from app.models.enums import (
    DeliveryVariantStatus,
    EditorExportStatus,
    JobOrigin,
    JobStatus,
    NotificationType,
    Operation,
    QualityTier,
)
from tests.conftest import auth_header
from tests.factories import make_job
from tests.integration.test_editor import _enable_editor, _open_cut, _video_asset


def _submit(db: Session, user: User, *, prompt: str = "海边的黄昏") -> object:
    return jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": prompt, "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job


def _job_notes(db: Session, user: User) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.target_type == "generation_job",
            )
        )
    )


def test_submit_creates_one_progress_notification(db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = _submit(db, author)
    notes = _job_notes(db, author)
    assert len(notes) == 1
    note = notes[0]
    assert note.type == NotificationType.JOB_PROGRESS
    assert note.title_key == "notification.job_queued"
    assert note.target_id == job.id
    assert note.payload_json["operation"] == Operation.TEXT_TO_IMAGE
    assert note.payload_json["status"] == JobStatus.CREATED
    assert note.payload_json["prompt_excerpt"] == "海边的黄昏"
    assert note.read_at is None


def test_job_transitions_update_the_same_notification_row(db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = _submit(db, author)
    note_id = _job_notes(db, author)[0].id

    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    sm.transition(db, job.id, JobStatus.SUCCEEDED)

    notes = _job_notes(db, author)
    assert len(notes) == 1
    note = notes[0]
    assert note.id == note_id
    assert note.type == NotificationType.JOB_SUCCEEDED
    assert note.title_key == "notification.job_succeeded"
    assert note.payload_json["status"] == JobStatus.SUCCEEDED
    assert note.read_at is None


def test_cancelled_and_expired_jobs_reuse_the_creation_row(db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    cancelled = _submit(db, author, prompt="取消")
    sm.transition(db, cancelled.id, JobStatus.CANCELLED)
    cancel_note = db.scalar(select(Notification).where(Notification.target_id == cancelled.id))
    assert cancel_note is not None
    assert cancel_note.type == NotificationType.JOB_CANCELLED
    assert cancel_note.title_key == "notification.job_cancelled"

    expired = _submit(db, author, prompt="超时")
    sm.transition(db, expired.id, JobStatus.EXPIRED)
    expire_note = db.scalar(select(Notification).where(Notification.target_id == expired.id))
    assert expire_note is not None
    assert expire_note.type == NotificationType.JOB_CANCELLED
    assert expire_note.title_key == "notification.job_expired"


def test_sandbox_jobs_never_write_consumer_notifications(db: Session, author: User) -> None:
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "沙盒", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        origin=JobOrigin.SANDBOX,
    ).job
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    sm.transition(db, job.id, JobStatus.SUCCEEDED)
    assert _job_notes(db, author) == []


def test_list_overlays_live_job_status(client: TestClient, db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = _submit(db, author)
    job.status = JobStatus.SUCCEEDED
    db.flush()

    body = client.get("/v1/notifications", headers=auth_header(author)).json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["type"] == NotificationType.JOB_SUCCEEDED
    assert item["title_key"] == "notification.job_succeeded"
    assert item["payload"]["status"] == JobStatus.SUCCEEDED
    assert "updated_at" in item


def test_export_queue_and_finish_share_one_notification(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable_editor(db, admin)
    opened = _open_cut(client, author, _video_asset(db, author))
    variant = DeliveryVariant(
        cut_revision_id=opened["cut"]["head_revision_id"],
        profile_key="douyin_9_16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        spec_json={"profile_key": "douyin_9_16"},
        spec_hash="n" * 64,
        status=DeliveryVariantStatus.READY,
    )
    db.add(variant)
    db.flush()

    queued = export_service.queue_exports(db, user_id=author.id, variant_ids=[variant.id])
    assert len(queued) == 1
    export = queued[0]
    first = db.scalar(
        select(Notification).where(
            Notification.user_id == author.id,
            Notification.target_type == "editor_export",
            Notification.target_id == export.id,
        )
    )
    assert first is not None
    assert first.type == NotificationType.JOB_PROGRESS
    assert first.title_key == "notification.export_queued"
    assert first.payload_json["operation"] == "drama_export"
    assert first.payload_json["cut_id"] == opened["cut"]["id"]

    editor_sm.transition_export(db, export.id, EditorExportStatus.CLAIMED)
    editor_sm.transition_export(db, export.id, EditorExportStatus.ENCODING)
    editor_sm.transition_export(db, export.id, EditorExportStatus.UPLOADING)
    editor_sm.transition_export(db, export.id, EditorExportStatus.VERIFYING)
    editor_sm.transition_export(db, export.id, EditorExportStatus.SUCCEEDED)

    notes = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == author.id,
                Notification.target_type == "editor_export",
            )
        )
    )
    assert len(notes) == 1
    assert notes[0].id == first.id
    assert notes[0].type == NotificationType.JOB_SUCCEEDED
    assert notes[0].title_key == "notification.export_succeeded"


def test_following_payload_includes_the_follower_handle(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    response = client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))
    assert response.status_code == 200
    note = db.scalar(
        select(Notification).where(
            Notification.user_id == author.id,
            Notification.type == NotificationType.NEW_FOLLOWER,
        )
    )
    assert note is not None
    assert note.payload_json["follower_handle"] == "remixer"
    assert note.payload_json["follower_display_name"] == "二创者"

    listed = client.get("/v1/notifications", headers=auth_header(author)).json()["items"][0]
    assert listed["payload"]["follower_handle"] == "remixer"


@pytest.mark.parametrize(
    "target_type",
    [
        notification_push.CREATION_TARGET_JOB,
        notification_push.CREATION_TARGET_EXPORT,
        notification_push.CREATION_TARGET_SCRIPT,
        notification_push.CREATION_TARGET_DRAFT,
    ],
)
def test_every_upserted_creation_target_is_unique_in_the_database(
    db: Session, author: User, target_type: str
) -> None:
    """`sync_creation_notification` relies on the partial unique index to turn
    a racing second insert into an update; a target type it upserts but the
    index skips would silently grow duplicate rows instead."""
    target_id = new_id("tgt")

    def row() -> Notification:
        return Notification(
            user_id=author.id,
            type=NotificationType.JOB_PROGRESS,
            title_key="notification.job_queued",
            payload_json={},
            target_type=target_type,
            target_id=target_id,
        )

    db.add(row())
    db.flush()

    nested = db.begin_nested()
    db.add(row())
    with pytest.raises(IntegrityError):
        db.flush()
    nested.rollback()


def test_an_asset_image_payload_names_its_card_and_look(db: Session, author: User) -> None:
    """Image notifications open the card workspace (`asset-job-href.ts`):
    the payload carries the kind, the target card and look up front, and
    the filed card once write-back sets it."""
    from app.domain.asset_variants import service as asset_variants_service
    from app.domain.scenes import service as scenes_service

    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="深夜便利店", description=None, reference_asset_ids=[]
    )
    variant_id = asset_variants_service.ensure_default(db, scene.skill).id
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={
            "prompt": "深夜便利店",
            "asset_kind": "scene",
            "target_scene_id": scene.id,
            "target_variant_id": variant_id,
        },
        idempotency_key=new_id("idk"),
    ).job
    payload = _job_notes(db, author)[0].payload_json
    assert payload["asset_kind"] == "scene"
    assert payload["target_scene_id"] == scene.id
    assert payload["target_variant_id"] == variant_id
    assert "linked_scene_id" not in payload

    job.linked_scene_id = scene.id
    sm.transition(db, job.id, JobStatus.QUEUED)
    payload = _job_notes(db, author)[0].payload_json
    assert payload["linked_scene_id"] == scene.id


def test_a_general_image_payload_names_no_card(db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    _submit(db, author)
    payload = _job_notes(db, author)[0].payload_json
    for key in (
        "asset_kind",
        "linked_character_id",
        "linked_scene_id",
        "linked_prop_id",
        "target_variant_id",
    ):
        assert key not in payload


def test_a_partial_delivery_payload_says_what_was_refunded(db: Session, author: User) -> None:
    """A 5-pose orbit job whose later passes failed succeeds with 1 image,
    settled pro rata (P2-0). The workspace shows only the image, so the
    notification carries the counts and the refund."""
    job = make_job(db, author, reserved=60, operation=Operation.IMAGE_TO_IMAGE)
    job.request_json = {
        "prompt": "转面",
        "asset_kind": "character",
        "camera_poses": [
            {"azimuth": a, "elevation": 0, "distance": 1} for a in (0, 45, 90, 180, 270)
        ],
    }
    job.status = JobStatus.SUCCEEDED
    job.output_asset_ids_json = [new_id("ast")]
    job.actual_credits = 12
    assert notification_push.partial_delivery(job) == {
        "delivered_outputs": 1,
        "requested_outputs": 5,
        "refunded_credits": 48,
    }

    job.output_asset_ids_json = [new_id("ast") for _ in range(5)]
    job.actual_credits = 60
    assert notification_push.partial_delivery(job) == {}
    job.status = JobStatus.FAILED
    job.output_asset_ids_json = None
    assert notification_push.partial_delivery(job) == {}
