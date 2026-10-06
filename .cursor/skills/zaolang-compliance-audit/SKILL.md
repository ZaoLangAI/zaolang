---
name: zaolang-compliance-audit
description: Audit trail, SystemLog, data export/deletion, real-person consent, retention purges, backups. Use when touching back/app/domain audit, system_log, compliance, consent, retention or ops/backups, data requests, or backup/restore.
---

# Compliance, Audit & Retention

**Scope**: `AuditLog`, `SystemLog` signals, data export/deletion, voice/portrait consent, retention purges, DB backups.
Not here → `zaolang-admin-console` (admin write pattern), `zaolang-media-assets` (uploads, `depicts_real_person`).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/audit/service.py` | `record()` (redacts before/after), `search()`, `REASON_REQUIRED_ACTIONS` |
| `back/app/domain/system_log/service.py` | `emit()` (dedup-window folding, optional `job_id`), `search()` |
| `back/app/api/v1/admin/logs.py` | `GET /v1/admin/logs`: audit + SystemLog merged, optional `job_id` |
| `back/app/domain/compliance/service.py` | `export_user_data`, `anonymise_user`, `signed_export_url`, `purge_expired_exports` |
| `back/app/api/v1/privacy.py` | `POST`/`GET /v1/me/data-requests`; admin `…/data-requests/{id}/decide` in `back/app/api/v1/admin/users.py` (deletion approval audited `data_request.approve_deletion`) |
| `back/app/domain/consent/service.py` | `assert_reference_consents`, `declare`, `revoke`, `revoke_all_for_user`; routes in `back/app/api/v1/uploads.py` |
| `back/app/domain/retention/service.py` | `purge_idempotency_records` (14 d), `purge_webhook_events` / `purge_system_logs` / `purge_job_events` (90 d) via `_delete_in_batches` |
| `back/app/domain/ops/backups.py` | `run_database_backup()`: `pg_dump` → storage `backups/db/` |
| `back/app/workers/tasks.py` | daily Beat tasks (`back/app/workers/celery_app.py`, queue `webhook_reconcile`): `purge_expired_exports`, `purge_expired_records`, `run_scheduled_backup` |
| `back/app/api/v1/admin/data.py` | `GET`/`POST /v1/admin/backups`, `/storage/usage`, `/storage/lifecycle` (audit `storage.lifecycle`), `/seed` (audit `data.seed`/`data.reset`) |
| `infra/scripts/backup.sh` | `make backup`: `pg_dump` to `.backups/`; no DB row |
| `infra/scripts/restore.sh` | refuses without `--confirm` (`make restore f=…` passes it) |

## Invariants

1. `AuditLog` is append-only; every `/v1/admin/*` write calls `audit.record(...)` explicitly (no decorator). Blank reason on a `REASON_REQUIRED_ACTIONS` action → `ReasonRequired`. `before`/`after` = summaries, never secrets/PII.
2. `SystemLog` is a folded signal projection, not audit: `emit` is best-effort (own `session_scope`, survives the request's rollback; dropped if Redis is down) and folds by `(source, event, dedup_key)` within `window_seconds`. Sources `auth`/`rate_limit`/`permission`/`moderation`/`pipeline`. `PIPELINE` rows carry `job_id` + raw exception (fold the job id into `dedup_key`); `JobEvent.public_message` stays user-safe.
3. Deletion = `anonymise_user`: PII scrubbed, works tombstoned with lineage kept, consents revoked. Never DELETE the user.
4. Export URL lives 900 s (`signed_export_url`); bundle purged after 30 days. Never log/email the URL.
5. `BackupRecord` has two writers sharing `run_database_backup`: admin `POST /backups` (`Admin` + confirm, `triggered_by_user_id`, audit `data.backup`) and Beat `run_scheduled_backup` (no user, no audit).
6. Retention windows = `*_RETENTION_DAYS`; only processed webhooks, system logs by `updated_at` (last fold), only events of terminal jobs whose `updated_at` is past the window; 5000-row batches. Never purge `AuditLog`/`CreditLedgerEntry`.
7. Consent: audio ref in `audio_generation` needs `VOICE`; `depicts_real_person` image/video ref needs `PORTRAIT`; `jobs.service.submit` → `assert_reference_consents` → `AssetRightsRequired`. A clone character voice (`characters.voices`, P7) checks the sample's active `VOICE` consent when it is created, and its jobs re-check it at submit like any clone. Clone voices unlock with a sold character: a buyer's job references the author's sample (never sent to the buyer) and passes on the author's declared consent for that asset; revoking that consent stops every buyer's clone jobs too. Audit (`consent.declare`/`revoke`) carries status only.
8. Log Center CSV export is client-side, not audited.
9. MinIO lifecycle rules (`back/app/storage/s3.py:lifecycle_rules`) must never match published objects.

## Recipes

**Add an audited action**: `audit.record(session, actor=…, action="domain.verb", …)`; high-risk → `REASON_REQUIRED_ACTIONS`; assert in `test_admin_security.py`.

**Add a retention purge**: function in `retention/service.py` calling `_delete_in_batches(session, Model.id, select(Model.id).where(...))` → add to the counts dict in `tasks.py:purge_expired_records` → test in `test_retention.py`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_compliance_audit.py tests/unit/test_retention.py tests/unit/test_scheduled_backup.py tests/unit/test_voice_consent.py tests/integration/test_admin_security.py tests/integration/test_admin_logs.py tests/integration/test_system_log.py -v
make backup
```
