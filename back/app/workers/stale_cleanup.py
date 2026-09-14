"""Classify leftover Celery broker messages and result-backend rows.

After a DB wipe (`make seed ARGS=--reset`) Redis still holds messages whose
`job_id` / analysis id no longer exist. Consuming those occupies a worker
slot and only yields `missing`. This module decides what is safe to drop
without touching rate-limit keys, LLM stats, or messages that still have a
matching row.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.workers.celery_app import celery_app

EntityTable = Literal["generation_jobs", "media_analyses"]

JOB_TASKS: frozenset[str] = frozenset(
    {
        "app.workers.tasks.run_generation",
        "app.workers.tasks.run_video_generation",
        "app.workers.tasks.run_audio_generation",
        "app.workers.tasks.run_video_analysis",
        "app.workers.tasks.run_quality_check",
    }
)

ANALYSIS_TASKS: frozenset[str] = frozenset(
    {
        "app.workers.tasks.run_media_analysis",
        "app.workers.tasks.run_editor_transcription",
        "app.workers.tasks.run_export_qa",
    }
)

KNOWN_APP_TASKS: frozenset[str] = frozenset(celery_app.conf.task_routes)


@dataclass(frozen=True, slots=True)
class DecodedTask:
    task: str
    task_id: str
    args: tuple[object, ...]
    entity_id: str | None


def decode_celery_message(raw: str | bytes) -> DecodedTask | None:
    """Parse a Redis list item written by the JSON Celery protocol.

    Undecodable envelopes return ``None`` so a cleaner can leave them alone
    rather than guess.
    """

    text = _as_text(raw)
    if text is None:
        return None
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    headers = envelope.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    task = headers.get("task") or ""
    if not isinstance(task, str) or not task:
        return None
    task_id = headers.get("id") or ""
    if not isinstance(task_id, str):
        task_id = str(task_id)
    args = _decode_args(envelope)
    entity_id = args[0] if args and isinstance(args[0], str) else None
    return DecodedTask(task=task, task_id=task_id, args=args, entity_id=entity_id)


def entity_table(task: str) -> EntityTable | None:
    if task in JOB_TASKS:
        return "generation_jobs"
    if task in ANALYSIS_TASKS:
        return "media_analyses"
    return None


def is_unknown_app_task(task: str) -> bool:
    return task.startswith("app.workers.") and task not in KNOWN_APP_TASKS


def is_orphan_message(decoded: DecodedTask, existing_ids: set[str]) -> bool:
    """True when this is a job/analysis task whose row is already gone."""

    if is_unknown_app_task(decoded.task):
        return True
    if entity_table(decoded.task) is None:
        return False
    if not decoded.entity_id:
        return False
    return decoded.entity_id not in existing_ids


def is_invalid_result(payload: dict[str, Any]) -> bool:
    """Celery result written after a broker message pointed at a missing row."""

    return payload.get("result") == "missing"


def parse_result_payload(raw: str | bytes) -> dict[str, Any] | None:
    text = _as_text(raw)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _as_text(raw: str | bytes) -> str | None:
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _decode_args(envelope: dict[str, Any]) -> tuple[object, ...]:
    body = envelope.get("body")
    if not isinstance(body, str) or not body:
        return ()
    properties = envelope.get("properties")
    encoding = "base64"
    if isinstance(properties, dict):
        raw_encoding = properties.get("body_encoding")
        if isinstance(raw_encoding, str) and raw_encoding:
            encoding = raw_encoding
    payload = _decode_body(body, encoding)
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        return tuple(payload[0])
    return ()


def _decode_body(body: str, encoding: str) -> object | None:
    try:
        if encoding == "base64":
            decoded = base64.b64decode(body)
            return json.loads(decoded)
        return json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return None
