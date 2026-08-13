"""Sandbox dry-run coverage for every `Operation`.

Stub path (this file, CI): `live_provider` omitted, LLM_MODE=stub. Asserts a
trace, no `GenerationJob` row, and no moderation-queue item keyed by the
fake dry-run id.

Live path with a real key is manual — not CI:

1. `make dev-api` (and for C-end video, `make dev-worker` including Beat).
2. `/admin/routing` → each Operation tab → 沙盒试跑 → check
   「真实调用已配置模型」. Reference ops need
   `{"reference_asset_ids":["ast_..."]}` (video: also `duration_seconds` 4–15).
3. Dialog shows a playable/viewable preview for that mime type.
4. C-end `/create/new?mode=...` preview-tier submit; the job page renders
   `<img>` / `<audio>` / `DevicePreview` from `output_media_type`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GenerationJob, ModerationQueueItem, ProviderAttempt, User
from app.models.enums import Operation
from tests.conftest import admin_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")

_VIDEO = {
    Operation.TEXT_TO_VIDEO.value,
    Operation.IMAGE_TO_VIDEO.value,
    Operation.VIDEO_TO_VIDEO.value,
}
_REFERENCE = {
    Operation.IMAGE_TO_IMAGE.value,
    Operation.IMAGE_TO_VIDEO.value,
    Operation.VIDEO_TO_VIDEO.value,
}


def _params(operation: str) -> dict[str, object]:
    params: dict[str, object] = {}
    if operation in _REFERENCE:
        params["reference_asset_ids"] = ["ast_missing"]
    if operation in _VIDEO:
        params["duration_seconds"] = 4
    return params


@pytest.mark.parametrize("operation", [op.value for op in Operation])
def test_stub_dry_run_covers_every_operation(
    client: TestClient, operator: User, db: Session, operation: str
) -> None:
    jobs_before = db.scalar(select(func.count()).select_from(GenerationJob)) or 0
    attempts_before = db.scalar(select(func.count()).select_from(ProviderAttempt)) or 0

    response = client.post(
        f"/v1/admin/workflow-templates/{operation}/dry-run",
        json={"prompt": "雨后的东京街头", "params": _params(operation)},
        headers=admin_header(operator),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["trace"]
    assert body.get("preview_url") in (None, "")
    assert (db.scalar(select(func.count()).select_from(GenerationJob)) or 0) == jobs_before
    assert (db.scalar(select(func.count()).select_from(ProviderAttempt)) or 0) == attempts_before
    queued = list(db.scalars(select(ModerationQueueItem.subject_id)).all())
    assert all(not sid.startswith("dry_") for sid in queued)


def test_needs_review_does_not_enqueue_a_fake_job(
    client: TestClient, operator: User, db: Session
) -> None:
    response = client.post(
        "/v1/admin/workflow-templates/text_to_image/dry-run",
        json={"prompt": "暴力的城市夜景"},
        headers=admin_header(operator),
    )
    assert response.status_code == 200, response.text
    queued = list(db.scalars(select(ModerationQueueItem.subject_id)).all())
    assert all(not sid.startswith("dry_") for sid in queued)


def test_a_dry_run_crash_returns_error_detail(
    client: TestClient, operator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self, ctx):  # type: ignore[no-untyped-def]
        raise RuntimeError("gateway down")

    monkeypatch.setattr("app.api.v1.admin.workflow_templates.WorkflowRunner.run", boom)
    response = client.post(
        "/v1/admin/workflow-templates/text_to_image/dry-run",
        json={"prompt": "雨后的东京街头"},
        headers=admin_header(operator),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["failure_code"] == "DRY_RUN_CRASHED"
    assert body["error_detail"]
    assert "RuntimeError" in body["error_detail"]
    assert "gateway down" in body["error_detail"]
