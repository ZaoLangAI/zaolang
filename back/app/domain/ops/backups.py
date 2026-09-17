"""Database backups: the `pg_dump` + object-storage upload shared by the
admin console's on-demand trigger (`api.v1.admin.data.trigger_backup`) and
the daily Celery Beat schedule (`app.workers.tasks.run_scheduled_backup`).

Before the scheduled task existed, a backup only ever happened when an
operator opened the admin console and clicked the button — this host had no
automation at all (confirmed by checking `crontab -l`/`systemctl list-timers`
on it directly), which is the gap this module's Beat-scheduled caller closes.
"""

from __future__ import annotations

import subprocess

from app.config import get_settings
from app.models.base import utcnow
from app.storage import s3

# pg_dump on a database this size should finish in well under a minute; ten
# minutes is headroom, not the expected case — matches the admin endpoint's
# prior inline value so scheduling this does not change its failure mode.
BACKUP_TIMEOUT_SECONDS = 600


def run_database_backup() -> tuple[str, int]:
    """Runs `pg_dump` and stores the archive in object storage.

    Returns the object key and byte size. Raises on any `pg_dump`/upload
    failure — callers decide how to surface that: the admin endpoint turns
    it into a `BackupRecord(status="failed")` row synchronously so an
    operator learns immediately; the scheduled task does the same, just
    without anyone watching the request finish.
    """
    settings = get_settings()
    # psycopg's SQLAlchemy prefix is not a libpq URL.
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    completed = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", dsn],
        capture_output=True,
        check=True,
        timeout=BACKUP_TIMEOUT_SECONDS,
    )
    key = f"backups/db/{utcnow():%Y%m%dT%H%M%SZ}.dump"
    s3.put_object(key, completed.stdout, content_type="application/octet-stream")
    return key, len(completed.stdout)
