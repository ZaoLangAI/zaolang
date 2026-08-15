---
name: zaolang-compliance-audit
description: Compliance capabilities — append-only AuditLog, user data export/deletion requests (deletion preserves lineage tombstones), MinIO object lifecycle policy, pg_dump backup and restore scripts. Use when changing audit logging, data export or deletion requests, user anonymisation, retention/lifecycle policies, or backup and restore.
disable-model-invocation: true
---

# Compliance, Audit & Data Retention

## Scope

Answers "who changed what, when, and why," and "what happens when a user asks to take or delete their data."

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/domain/audit/service.py` | `record()` / `search()`, automatically attaching actor, role, request_id, IP, UA |
| `back/app/domain/system_log/service.py` | `emit()` (windowed aggregation) / `search()` for security signals (failed logins, rate limiting, auth rejections); both `emit()` and `search()` take an optional `job_id` to tie pipeline/worker runtime-error signals to a specific generation job |
| `back/app/domain/compliance/service.py` | `export_user_data` / `anonymise_user` / `signed_export_url` / `purge_expired_exports` |
| `back/app/api/v1/privacy.py` | user-facing export and deletion-request entry points |
| `back/app/api/v1/admin/users.py` | admin approval of `DataRequest` |
| `back/app/api/v1/admin/data.py` | backup triggers, lifecycle policy, seed/reset |
| `infra/scripts/backup.sh` / `restore.sh` | `pg_dump` / `pg_restore`, backing `make backup` / `make restore` |
| `back/app/models/platform.py` | `AuditLog` / `DataRequest` / `BackupRecord` |
| `back/app/models/system_log.py` | `SystemLog` (a security-signal aggregation projection, not a replacement for AuditLog) |

## Invariants

1. **`AuditLog` is append-only** — never UPDATE or DELETE. Fields include actor, role, target object, a **before/after value summary**, reason, request_id, IP, UA.
2. **`SystemLog` is a side-channel aggregation projection** for high-frequency security signals (failed logins, rate limiting, auth rejections) **and key runtime-error signals** (`SystemLogSource.PIPELINE`: top-level crashes in `pipeline.py`, `WorkflowRunner._engine_failure`, capability-missing/timeout abandonment during async-provider polling, Celery task-boundary fallback failures), with windowed count-folding to avoid write storms; it **does not replace** `AuditLog` or the various business-specific tables. Runtime-error signals carry `job_id` so the admin job-detail view can answer "exactly where did this job crash" — `JobEvent.public_message` stays the vague user-facing text; the raw exception only goes into `SystemLog.message`. Don't mix the two.
3. **Every `/v1/admin/*` write must be audited**, handled uniformly by the audit decorator. Forgetting to attach the decorator to a new admin write endpoint is the easiest mistake to make in this repo, and the hardest to notice.
4. **High-risk operations require a mandatory reason**: adjustments, tombstoning, bans, config rollbacks, forced job termination, switching an agent's model, triggering a restore. Missing a reason must raise `ReasonRequired` — never accept an empty string.
5. **Deleting a user means anonymisation, not DELETE**: `anonymise_user` scrubs PII while keeping `Work` / `WorkVersion` / `LineageEdge` as tombstone nodes. **Downstream remixes' provenance must not vanish** — this is a lineage-integrity requirement, and the reason `LineageProtected` exists.
6. **Exports are time-limited**: `export_user_data` writes to object storage and is delivered only via a short-lived signed URL (900s default); `purge_expired_exports` cleans up after expiry. Never put an export URL in an email or a log line.
7. **Backups are recorded in `BackupRecord`**: who triggered it, the result, the file location. The restore script requires an explicit `--confirm` — no "run it by accident" path.
8. **Audit logs are searchable and exportable, but exporting them is itself an audited event.**

## Extension Points

- **Add an audited operation**: call `audit.record(...)` from the domain function; `before`/`after` hold only a summary, **never sensitive raw values** (keys, passwords, full PII). Add the corresponding assertion to `tests/integration/test_admin_security.py`.
- **Add a data-request type**: add a value to `DataRequestType` → branch the approval flow → add a handling entry point in the admin `data-requests-panel.tsx`.
- **Change retention policy**: MinIO lifecycle rules live in `app/storage/s3.py`'s `lifecycle_rules` / `put_lifecycle_rules`, visualized in the admin `lifecycle-panel.tsx`. Before changing a rule, confirm it won't accidentally delete published assets (staging prefixes and the published area must stay separate).

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_compliance_audit.py tests/integration/test_admin_security.py -v
make backup          # produces .backups/*.dump and records a BackupRecord
```

Manual path: perform a manual credit adjustment in admin → `/admin/audit` (Log Center) should show the record with its reason; file and approve a deletion request for a seed user → after anonymisation, their work should remain a lineage tombstone, not disappear.
