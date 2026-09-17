"""Drop orphaned Celery broker messages and leftover result keys.

Does not ``FLUSHDB``: rate-limit windows, LLM failover stats, and kombu
bindings stay put. Periodic Beat ticks are kept. Only messages whose
generation-job / media-analysis row is gone (or whose task name is no
longer registered) are removed from the queues.

Usage:
    python -m app.scripts.purge_stale_celery
    python -m app.scripts.purge_stale_celery --results
    python -m app.scripts.purge_stale_celery --empty-queues
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from app.api.rate_limit import get_redis
from app.db import session_scope
from app.models import GenerationJob, MediaAnalysis
from app.workers.celery_app import QUEUE_NAMES
from app.workers.stale_cleanup import (
    DecodedTask,
    decode_celery_message,
    entity_table,
    is_invalid_result,
    is_orphan_message,
    parse_result_payload,
)

logger = logging.getLogger("purge_stale_celery")

RESULT_KEY_PREFIX = "celery-task-meta-"


@dataclass(slots=True)
class PurgeReport:
    scanned: int = 0
    dropped_messages: int = 0
    kept_messages: int = 0
    undecodable: int = 0
    dropped_results: int = 0
    emptied_queues: list[str] = field(default_factory=list)
    by_task: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def as_text(self) -> str:
        lines = [
            f"scanned_messages={self.scanned}",
            f"dropped_messages={self.dropped_messages}",
            f"kept_messages={self.kept_messages}",
            f"undecodable={self.undecodable}",
            f"dropped_results={self.dropped_results}",
        ]
        if self.emptied_queues:
            lines.append(f"emptied_queues={','.join(self.emptied_queues)}")
        if self.by_task:
            detail = ", ".join(f"{name}:{count}" for name, count in sorted(self.by_task.items()))
            lines.append(f"dropped_by_task={detail}")
        return "\n".join(lines)


def run(*, drop_all_results: bool = False, empty_queues: bool = False) -> PurgeReport:
    report = PurgeReport()
    client = get_redis()

    if empty_queues:
        for name in QUEUE_NAMES:
            deleted = int(client.delete(name) or 0)
            if deleted:
                report.emptied_queues.append(name)
    else:
        _drop_orphan_messages(client, report)

    report.dropped_results = _drop_result_keys(client, drop_all=drop_all_results)
    return report


def _drop_orphan_messages(client, report: PurgeReport) -> None:  # type: ignore[no-untyped-def]
    pending: list[tuple[str, str, DecodedTask]] = []
    job_ids: set[str] = set()
    analysis_ids: set[str] = set()

    for queue in QUEUE_NAMES:
        items = client.lrange(queue, 0, -1) or []
        for raw in items:
            report.scanned += 1
            decoded = decode_celery_message(raw)
            if decoded is None:
                report.undecodable += 1
                report.kept_messages += 1
                continue
            pending.append((queue, raw, decoded))
            table = entity_table(decoded.task)
            if table == "generation_jobs" and decoded.entity_id:
                job_ids.add(decoded.entity_id)
            elif table == "media_analyses" and decoded.entity_id:
                analysis_ids.add(decoded.entity_id)

    existing = _existing_ids(job_ids, analysis_ids)
    for queue, raw, decoded in pending:
        if not is_orphan_message(decoded, existing):
            report.kept_messages += 1
            continue
        removed = int(client.lrem(queue, 1, raw) or 0)
        if removed:
            report.dropped_messages += 1
            report.by_task[decoded.task] += 1
        else:
            # Already consumed between LRANGE and LREM — not an error.
            report.kept_messages += 1


def _existing_ids(job_ids: set[str], analysis_ids: set[str]) -> set[str]:
    found: set[str] = set()
    if not job_ids and not analysis_ids:
        return found
    with session_scope() as session:
        if job_ids:
            found.update(
                session.scalars(select(GenerationJob.id).where(GenerationJob.id.in_(job_ids)))
            )
        if analysis_ids:
            found.update(
                session.scalars(select(MediaAnalysis.id).where(MediaAnalysis.id.in_(analysis_ids)))
            )
    return found


def _drop_result_keys(client, *, drop_all: bool) -> int:  # type: ignore[no-untyped-def]
    deleted = 0
    batch: list[str] = []
    for key in client.scan_iter(f"{RESULT_KEY_PREFIX}*", count=200):
        if drop_all:
            batch.append(key)
        else:
            payload = parse_result_payload(client.get(key) or b"")
            if payload is not None and is_invalid_result(payload):
                batch.append(key)
        if len(batch) >= 200:
            deleted += int(client.delete(*batch) or 0)
            batch.clear()
    if batch:
        deleted += int(client.delete(*batch) or 0)
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 Redis 里失效的 Celery 消息与结果")
    parser.add_argument(
        "--results",
        action="store_true",
        help="同时删除全部 celery-task-meta（业务进度走 JobEvent/SSE，不读这份结果）",
    )
    parser.add_argument(
        "--empty-queues",
        action="store_true",
        help="直接清空 QUEUE_NAMES 列表（会丢掉尚未消费的有效任务，清库后才用）",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = run(drop_all_results=args.results, empty_queues=args.empty_queues)
    print(report.as_text())


if __name__ == "__main__":
    main()
