"""Orphan Celery broker messages must be droppable without guessing."""

from __future__ import annotations

import base64
import json

from app.workers.celery_app import celery_app
from app.workers.stale_cleanup import (
    decode_celery_message,
    is_invalid_result,
    is_orphan_message,
    is_unknown_app_task,
    parse_result_payload,
)


def _envelope(
    *,
    task: str,
    args: list[object],
    task_id: str = "11111111-1111-1111-1111-111111111111",
    body_encoding: str = "base64",
) -> str:
    payload = [args, {}, {"callbacks": None, "errbacks": None, "chain": None, "chord": None}]
    encoded = json.dumps(payload)
    body = base64.b64encode(encoded.encode()).decode() if body_encoding == "base64" else encoded
    return json.dumps(
        {
            "body": body,
            "headers": {"task": task, "id": task_id},
            "properties": {"body_encoding": body_encoding},
        }
    )


def test_decode_reads_job_id_from_base64_body() -> None:
    raw = _envelope(task="app.workers.tasks.run_generation", args=["job_abc"])
    decoded = decode_celery_message(raw)
    assert decoded is not None
    assert decoded.entity_id == "job_abc"
    assert decoded.task == "app.workers.tasks.run_generation"


def test_decode_accepts_utf8_body() -> None:
    raw = _envelope(
        task="app.workers.tasks.run_media_analysis",
        args=["man_abc"],
        body_encoding="utf-8",
    )
    decoded = decode_celery_message(raw)
    assert decoded is not None
    assert decoded.entity_id == "man_abc"


def test_undecodable_envelope_is_left_alone() -> None:
    assert decode_celery_message("not-json") is None
    assert decode_celery_message(b"\xff\xfe") is None


def test_orphan_job_message_is_dropped_existing_is_kept() -> None:
    decoded = decode_celery_message(
        _envelope(task="app.workers.tasks.run_video_generation", args=["job_gone"])
    )
    assert decoded is not None
    assert is_orphan_message(decoded, set())
    assert not is_orphan_message(decoded, {"job_gone"})


def test_periodic_tick_is_never_treated_as_orphan() -> None:
    decoded = decode_celery_message(
        _envelope(task="app.workers.tasks.poll_async_provider_tasks", args=[])
    )
    assert decoded is not None
    assert not is_orphan_message(decoded, set())


def test_renamed_worker_task_is_dropped() -> None:
    decoded = decode_celery_message(_envelope(task="app.workers.tasks.run_legacy", args=["job_x"]))
    assert decoded is not None
    assert is_unknown_app_task(decoded.task)
    assert is_orphan_message(decoded, {"job_x"})


def test_missing_result_is_invalid() -> None:
    assert is_invalid_result({"status": "SUCCESS", "result": "missing"})
    assert not is_invalid_result({"status": "SUCCESS", "result": 3})
    assert parse_result_payload('{"result": "missing"}') == {"result": "missing"}


def test_celery_does_not_store_results_in_redis() -> None:
    assert celery_app.conf.task_ignore_result is True
