"""`app.workers.tasks.run_scheduled_backup` — the daily automated backup this
host never had (no crontab entry, no systemd timer, confirmed directly on
the production box), and the failure path that must not crash the Beat tick.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.domain.ops import backups as backups_service
from app.models import BackupRecord


def _fake_scope_factory(session: Session):
    @contextmanager
    def _fake_scope():
        yield session

    return _fake_scope


def test_run_scheduled_backup_records_a_succeeded_row(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import tasks

    monkeypatch.setattr(tasks, "session_scope", _fake_scope_factory(db))
    monkeypatch.setattr(
        backups_service, "run_database_backup", lambda: ("backups/db/fake.dump", 1234)
    )

    record_id = tasks.run_scheduled_backup()

    record = db.get(BackupRecord, record_id)
    assert record is not None
    assert record.kind == "database"
    assert record.status == "succeeded"
    assert record.object_key == "backups/db/fake.dump"
    assert record.size_bytes == 1234
    # No operator triggered this tick — unlike the admin console's button.
    assert record.triggered_by_user_id is None


def test_run_scheduled_backup_records_a_failed_row_without_raising(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `pg_dump`/upload failure must not crash the Beat tick — the next
    scheduled attempt (and the admin console's manual button) both still
    need to run normally afterwards."""
    from app.workers import tasks

    monkeypatch.setattr(tasks, "session_scope", _fake_scope_factory(db))

    def _boom() -> tuple[str, int]:
        raise RuntimeError("pg_dump: connection refused")

    monkeypatch.setattr(backups_service, "run_database_backup", _boom)

    record_id = tasks.run_scheduled_backup()

    record = db.get(BackupRecord, record_id)
    assert record is not None
    assert record.status == "failed"
    assert "pg_dump: connection refused" in (record.message or "")
