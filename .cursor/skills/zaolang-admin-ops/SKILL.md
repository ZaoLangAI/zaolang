---
name: zaolang-admin-ops
description: Behaviour of each back-office domain — health probes, job terminate/requeue, model endpoints, workflow templates, sandbox runs, moderation queue/appeals, keyword gates, config, data ops. Use when editing back/app/api/v1/admin/*, admin console pages, moderation_queue or moderation_policy.
---

# Admin Operations Domains

**Scope**: behaviour and data sources of each `/v1/admin/*` domain and its console page; the shared human-review queue (`moderation_queue`) and keyword gates (`moderation_policy`).
Not here → `zaolang-admin-console` (shell, RBAC, audit pattern), `zaolang-admin-statistics` (trends), `zaolang-credits-billing` (ledger), `zaolang-compliance-audit` (backups, retention), `zaolang-generation-jobs` (workflow runtime), `zaolang-agent-gateway` (providers), `zaolang-creation-library` (skills).

## Key Paths

| Path | What |
|---|---|
| `back/app/api/v1/admin/` | one router per domain, mounted in `__init__.py`; domain → file → page map in `reference-routes.md` |
| `front/src/app/[locale]/(admin)/admin/(console)/` | one `page.tsx` dir per domain |
| `front/src/components/admin/` | shared primitives at top level + one dir per domain (see zaolang-admin-console) |
| `back/app/domain/moderation_queue/service.py` | `enqueue_for_review`, `ensure_work_queue_item`, `latest_work_queue_item`, `open_report_count`, priority scoring |
| `back/app/domain/moderation_policy.py` | `assert_allowed` / `record_block_signal` keyword gates, `SAFE_REJECTION_MESSAGE`, `text_values` |
| `front/src/lib/admin/operations.ts` | operation lists, `MEDIA_PROTOCOLS` / `IMPLEMENTED_MEDIA_PROTOCOLS` mirror, `operationHasAssetKinds` |
| `front/src/lib/admin/` | also `copy-routing.ts` (copy-agent slot/template), `token-count.ts` + `micro-usd.ts` (form parsing), `tool-grants.ts` (labels), `upload.ts` (style-gallery cover) |

## Invariants

1. Health probes report, never repair; failure → `healthy=False`, never raises (`observability.py:_probe`). Probe SQL uses `_isolated_query` (`begin_nested`) so it can't poison the request transaction.
2. `async_provider_polling` probe (overdue unclaimed `AsyncProviderTask`) is the only dead-Beat signal. Queues: `QUEUE_NAMES` in `back/app/workers/celery_app.py`; a new one also goes in Makefile `dev-worker -Q`.
3. Terminate uses `sm.transition` (never a raw UPDATE), releases the reserve if `release_credits` (default true), first tries `cancel_upstream` for an in-flight provider task (failure only logs) → `jobs.py:terminate`.
4. Requeue only for non-terminal jobs; reuses the same job and reservation, no new reserve → `jobs.py:requeue`.
5. New `ProviderStat` row: `default=0` applies only at flush — flush before `+=` (`back/app/agents/router.py`).
6. `decide` appends a human `ModerationResult` (never edits the agent's). Work `REJECTED` → `publishing.hide` (reversible); tombstone is separate and terminal. `generation_job` subjects only get the result row → `content.py:_apply_work_decision`.
7. Reports and appeals are separate tables; `WorkAppeal` only by owner for `HIDDEN` works (`back/app/api/v1/works.py`); never reuse `ReportStatus.APPEALED`.
8. `enqueue_for_review`: one row per `(subject_type, subject_id, stage)` (`uq_moderation_queue_subject`); open row only refreshes reason/priority (claim kept), resolved row reopens. Priority = stage base + 10/category + 15/open report. All `needs_review` producers use it.
9. `ensure_work_queue_item` finds/creates the `pre_publish` row for a work Safety auto-approved; it never rewrites an existing row's status.
10. `assert_allowed(config_key=…)` checks `blocked_keywords` (`content_moderation`/`learning_moderation`/`skill_moderation`), emits a `MODERATION` SystemLog, raises `ValidationFailed(reason_code="PROHIBITED_CONTENT")` with the generic message — never echo the keyword.
11. Templates are keyed by `(operation, asset_kind)`; `canonical_operation` folds each image/video family onto `text_to_image`/`text_to_video`; `get_active` falls back to `asset_kind=NULL` (`back/app/domain/workflow_templates/service.py`). Console kind picker is image-only (`operationHasAssetKinds`).
12. `ensure_default_templates` seeds only empty buckets — editing `back/app/workflows/defaults.py` never reaches existing DBs; ship a data migration patching active rows' `graph_json`.
13. Media endpoint `generation_kind=edit` is routing, not a label: hidden from `text_to_video`/`image_to_video` model lists and hard-filtered without a video source → `back/app/agents/router.py:_request_constraint_failure`.
14. `protocol` must be in `IMPLEMENTED_MEDIA_PROTOCOLS` (`back/app/platform_config/schemas.py`); others 422, never fall back to OpenAI. Image-output endpoints have a 90 000 ms timeout floor (`MEDIA_IMAGE_TIMEOUT_MS_MIN`).
15. Sandbox-run = real `GenerationJob(origin=sandbox)` (+`graph_override_json` for drafts), no credits; `debug-chat` makes real model calls. Never revert to a dry run.
16. Every feature flag needs a label in `config.py:FLAG_DESCRIPTIONS` (test asserts set equality with `FEATURE_FLAG_NAMES`).
17. `seed`/`reset` refused when `settings.is_production` → `data.py`, test `test_seeding_is_refused_in_production`.
18. Announcement kinds `notice`/`maintenance`/`incident` (`AnnouncementRequest.kind` in `back/app/api/schemas/admin.py` = `KINDS` in `announcements-console.tsx`).
19. Agent `default_for_asset_kind` accepts `ASSET_KIND_BUCKETS` + `copy` (`back/app/domain/agent_skills/service.py`); the dialog dropdown offers only image kinds + `copy`.

## Recipes

**Add a health probe**: add `_probe("name", fn)` in `observability.py:system_health` → card in `health/health-cards.tsx` → query via `_isolated_query`.

**Add a bulk action**: accept a list of IDs, call the single-item domain function per item (keeps validation + per-item audit); no bulk UPDATE.

**Add a moderation producer**: call `moderation_queue.enqueue_for_review(subject_type, subject_id, stage, reason_code, categories)`; add detail/thumbnail handling in `content.py:moderation_detail` and `subject-thumb.tsx`.

**Add a keyword-gated surface**: `KeywordModerationConfig` subclass + key in `back/app/platform_config/schemas.py` → `assert_allowed(session, config_key=…, texts=text_values(params), subject_type=…)` before persisting.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_ops_runtime.py tests/integration/test_admin_ops_domain.py tests/integration/test_admin_ops_platform.py tests/integration/test_admin_llm_providers.py tests/unit/test_moderation_domains.py -v
make test-e2e   # front/e2e/flows/admin.spec.ts
```

`make seed` plants accounts, system defaults, and the `zaolang_studio` skill catalogue (see zaolang-creation-library); job/moderation/credit pages stay empty until real data exists.

## References

- `reference-routes.md` — read when locating which admin router, route, page and component own a domain.
