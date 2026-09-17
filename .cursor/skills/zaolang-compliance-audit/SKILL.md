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
| `back/app/domain/system_log/service.py` | `emit()` (windowed aggregation) / `search()` for security signals (failed logins, rate limiting, auth rejections); both `emit()` and `search()` take an optional `job_id` to tie pipeline/worker runtime-error signals to a specific generation job. `SystemLogSource` is `AUTH` / `RATE_LIMIT` / `PERMISSION` / `MODERATION` / `PIPELINE` — check `models/enums.py` before adding a source, the Log Center's source filter and its trilingual `source.*` labels key off it |
| `back/app/api/v1/admin/logs.py` | the unified `GET /v1/admin/logs`: merges `audit.search()` rows and `SystemLog` rows into one time-ordered `Page[LogEntryView]` (`source=audit` or a `SystemLogSource`, `level`, `actor_user_id`, `q`, date range, cursor); `job_id` OR's audit rows with `target_type="generation_job"` against `SystemLog` rows carrying that `job_id` so the jobs console's "related logs" shows deliberate operator actions and runtime crashes in one list |
| `back/app/domain/compliance/service.py` | `export_user_data` / `anonymise_user` / `signed_export_url` / `purge_expired_exports` |
| `back/app/api/v1/privacy.py` | user-facing export and deletion-request entry points |
| `back/app/api/v1/admin/users.py` | admin approval of `DataRequest` |
| `back/app/api/v1/admin/data.py` | `GET`/`POST /v1/admin/backups` (the only writer of `BackupRecord`), lifecycle policy, seed/reset |
| `infra/scripts/backup.sh` / `restore.sh` | `pg_dump --format=custom` to `.backups/zaolang-<stamp>.dump` (optional `mc cp` to `s3://$S3_BUCKET/backups/db/`, prunes to `BACKUP_KEEP`) / `pg_restore`, backing `make backup` / `make restore`; shell-only, no database row |
| `back/app/models/platform.py` | `AuditLog` / `DataRequest` / `BackupRecord` |
| `back/app/models/system_log.py` | `SystemLog` (a security-signal aggregation projection, not a replacement for AuditLog) |

## Invariants

1. **`AuditLog` is append-only** — never UPDATE or DELETE. Fields include actor, role, target object, a **before/after value summary**, reason, request_id, IP, UA.
2. **`SystemLog` is a side-channel aggregation projection** for high-frequency security signals (failed logins, rate limiting, auth rejections) **and key runtime-error signals** (`SystemLogSource.PIPELINE`: top-level crashes in `pipeline.py`, `WorkflowRunner._engine_failure`, capability-missing/timeout abandonment during async-provider polling, Celery task-boundary fallback failures), with windowed count-folding to avoid write storms; it **does not replace** `AuditLog` or the various business-specific tables. Runtime-error signals carry `job_id` so the admin job-detail view can answer "exactly where did this job crash" — `JobEvent.public_message` stays the vague user-facing text; the raw exception only goes into `SystemLog.message`. Don't mix the two.
3. **Every `/v1/admin/*` write must be audited** — by an explicit `audit.record(session, actor=user, action=..., target_type=..., target_id=..., before=..., after=..., reason=..., request=request)` call in the route (or the domain function it delegates to) before `session.commit()`. There is no decorator or middleware doing this for you: forgetting the call on a new admin write endpoint is the easiest mistake to make in this repo, and the hardest to notice. Grep `audit.record` in a sibling file under `api/v1/admin/` for the `action` naming convention (`data.backup`, `user.suspend`, ...).
4. **High-risk operations require a mandatory reason**: adjustments, tombstoning, bans, config rollbacks, forced job termination, switching an agent's model, triggering a restore. Missing a reason must raise `ReasonRequired` — never accept an empty string.
5. **Deleting a user means anonymisation, not DELETE**: `anonymise_user` scrubs PII while keeping `Work` / `WorkVersion` / `LineageEdge` as tombstone nodes. **Downstream remixes' provenance must not vanish** — this is a lineage-integrity requirement, and the reason `LineageProtected` exists.
6. **Exports are time-limited, on two different clocks**: `export_user_data` writes a JSON bundle to object storage and it is delivered only via `signed_export_url(object_key, expires_in=900)` — a presigned GET that dies after 15 minutes and is re-minted on each download request. The object itself lives longer: `purge_expired_exports(older_than_days=30)` deletes the stored bundle of `COMPLETED` `EXPORT` `DataRequest`s whose `handled_at` is older than 30 days and clears `result_object_key`. Don't confuse the URL TTL with the retention window. Never put an export URL in an email or a log line.
7. **Console backups are recorded in `BackupRecord`; shell backups are not.** Admin `POST /v1/admin/backups` (`admin_dangerous` bucket, `confirm` + `reason` required) creates the `BackupRecord` (`triggered_by_user_id`, `status` running → succeeded/failed, `object_key`, `size_bytes`, `message`), runs `pg_dump` synchronously into object storage, and writes an `audit.record(action="data.backup")`. `make backup` (`infra/scripts/backup.sh`) is the operator's shell path: it only `pg_dump`s to `.backups/` (uploading beside the console's archives when `mc` + `S3_BUCKET` are configured) and touches no database row. The restore script requires an explicit `--confirm` — no "run it by accident" path.
8. **Audit logs are searchable; the Log Center's CSV export is a client-side convenience, not an audited event.** `log-center-console.tsx`'s `exportCsv` serialises the rows already fetched from `GET /v1/admin/logs` into a `Blob` in the browser — the server never sees an "export" call, so nothing is recorded. If a compliance requirement ever needs "who exported the audit trail", add a server-side export endpoint that `audit.record`s itself; don't assume the current button does.
9. **A real person's voice or likeness needs that person's consent before it can feed a generation** (深度合成管理规定 §14). `app/domain/consent/service.py` owns it: a voice-clone sample, or a reference its uploader flagged `depicts_real_person`, is refused at `jobs.service.submit` with `AssetRightsRequired` until an active `AssetConsent` of the matching type exists. Declaring and revoking are the owner's own actions on their own assets, audited as `consent.declare` / `consent.revoke` — `before`/`after` carry status only, never the subject's name. `anonymise_user` revokes every consent the user declared or that covers their assets (`revoke_all_for_user`), so a deleted account's voice cannot keep authorising clones. Details and known limits live in `zaolang-media-assets` invariant #8.

## Extension Points

- **Add an audited operation**: call `audit.record(...)` from the domain function; `before`/`after` hold only a summary, **never sensitive raw values** (keys, passwords, full PII). Add the corresponding assertion to `tests/integration/test_admin_security.py`.
- **Add a data-request type**: add a value to `DataRequestType` → branch the approval flow → add a handling entry point in the admin `data-requests-panel.tsx`.
- **Change retention policy**: MinIO lifecycle rules live in `app/storage/s3.py`'s `lifecycle_rules` / `put_lifecycle_rules`, visualized in the admin `lifecycle-panel.tsx`. Before changing a rule, confirm it won't accidentally delete published assets (staging prefixes and the published area must stay separate).

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_compliance_audit.py tests/integration/test_admin_security.py -v
make backup          # produces .backups/zaolang-*.dump only; a BackupRecord row comes from admin POST /v1/admin/backups
```

Manual path: perform a manual credit adjustment in admin → `/admin/audit` (Log Center) should show the record with its reason; file and approve a deletion request for a seed user → after anonymisation, their work should remain a lineage tombstone, not disappear.
