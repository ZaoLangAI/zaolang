---
name: zaolang-generation-jobs
description: Generation job lifecycle — state machine, JobEvent/SSE resume, Celery queues/Beat, async polling, cancel/retry/fast-retry, terminal-job hook, workflow graphs/templates, video analysis. Use when editing back/app/domain/jobs, back/app/workers, back/app/workflows, /v1/generation-jobs, use-job-stream.
---

# Generation Jobs & Queues

**Scope**: turn a generation request into a trackable, replayable, settleable `GenerationJob`. State machine + JobEvent stream is the only progress truth — never keep a second copy. Submitters: `back/app/api/v1/jobs.py` (studios), the canvas Agent, and the admin sandbox, all via `jobs_service.submit`.

Not here → `zaolang-agent-gateway` (routing, provider quirks, character-sheet view prompts, planner), `zaolang-data-model` (`latest_job_id`/`applied_job_id`, status tables, migrations), `zaolang-credits-billing` (reserve/settle/refund), `zaolang-platform-config` (flags), `zaolang-api-contract` (idempotency, errors), `zaolang-canvas` (canvas landing).

## Key Paths

| Path | What |
| --- | --- |
| `back/app/models/enums.py` | `JobStatus`, `JOB_TRANSITIONS`, `TERMINAL_JOB_STATUSES`, `CANCELLABLE_JOB_STATUSES`, `JobEventType`, `JobOrigin`, `MediaGenerationKind` |
| `back/app/domain/jobs/state_machine.py` | `transition` / `request_cancel` / `append_event` / `events_since` |
| `back/app/domain/jobs/service.py` | `quote_for` / `submit` / `settle_success` / `settle_release` / `get_owned_job` |
| `back/app/domain/jobs/dispatch.py` | `enqueue_or_fail` — post-commit broker hand-off shared by every credit-reserving surface |
| `back/app/domain/jobs/completion.py` | `on_job_terminal` — the single terminal-job hook |
| `back/app/domain/jobs/cancellation.py` | `should_honor_immediately` / `honor_user_cancel` / `ack_cancel_request` |
| `back/app/domain/jobs/async_tasks.py` | `AsyncProviderTask` suspend/`claim_due`/reschedule/settle, `cancel_upstream`, `POLL_INTERVAL_SECONDS`, `MAX_POLL_DURATION_SECONDS` |
| `back/app/domain/jobs/input_requests.py` | `AWAITING_INPUT` (`WorkflowInputRequest`): suspend/answer/expire, `INPUT_TIMEOUT_SECONDS` |
| `back/app/domain/jobs/fast_retry.py` | `build_seed` — retry eligibility to start at `route_score` |
| `back/app/workers/celery_app.py` | `QUEUE_NAMES` (ground truth), `task_routes`, `beat_schedule`, `visibility_timeout` |
| queues | `image_generation` `video_generation_long` `audio_generation` `quality_check` `webhook_reconcile` `provider_task_polling` `media_analysis` `platform_distribution` `video_analysis` (test_skill_freshness enforces) |
| `back/app/workers/tasks.py` | Celery entry points, per-task time-limit dicts, `dispatch_generation` (operation → task/queue), `image_generation_time_limits`, `GenerationTask.on_failure` (settles a job the pipeline could not), `STALE_JOB_TIMEOUT` (30 min) |
| `back/app/workers/pipeline.py` | `run_generation_pipeline` / `resolve_graph` / `_apply_fast_retry_seed`; top-level crash contract |
| `back/app/workers/async_polling.py` | `poll_once` — Beat-driven poll/resume/cancel/give-up |
| `back/app/workers/stale_cleanup.py` | orphan broker messages for `make dev-purge-queues` |
| `back/app/workflows/` | graph engine: `runner.py`, `nodes.py` (executors), `defaults.py` (code graphs), `registry.py`, `configs.py` |
| `back/app/domain/workflow_templates/service.py` | `get_active` / `canonical_operation` / `ensure_default_templates` |
| `back/app/realtime/publisher.py` | Redis pubsub: job, per-user notification, and canvas channel families; best-effort (errors logged) |
| `back/app/api/v1/jobs.py` | submit, quote, `quote:batch` (see `zaolang-credits-billing`), `/models`, list, cancel, retry, promote, input-request/answer, SSE `/v1/generation-jobs/{id}/events` |
| `back/app/api/v1/admin/workflow_templates.py` | sandbox-run / sandbox-runs (real job, `origin=sandbox`) |
| `back/app/api/v1/admin/jobs.py` | admin job ops, `terminate`, `requeue`, admin input-request/answer, admin SSE (adds `node_id`) |
| `front/src/lib/use-job-stream.ts` | consumer SSE hook (admin: `use-admin-job-stream.ts`); studios keep one instance and swap `jobId` in place |
| `front/src/components/job/` | `job-progress.tsx`, shared event→stage table `job-stages.ts`, awaiting-input panel |
| `front/src/features/video-analysis/` | video-analysis tool UI (studio/upload/progress/result/history/api) |
| `front/src/app/[locale]/(site)/create/tools/video-analysis/page.tsx` | video-analysis route |

## Invariants

1. Status changes only via `state_machine.transition` (conditional UPDATE `WHERE status IN …`). Terminal states have no out-edges → `InvalidJobTransition`; this is what drops late/duplicate provider callbacks. Exactly one terminal write wins.
2. `CREATED → EXPIRED` must stay legal: a job the broker never picked up still has to release its reservation (`expire_stale_jobs`, Beat 300s).
3. Terminal landing writes `finished_at` and settles: success → `settle_success`, else `settle_release`. Sandbox settle is a no-op (`skips_credits`).
4. `JobEvent.sequence` starts at 1, no gaps/dupes. SSE replays from DB via `Last-Event-ID`, then tails Redis, skipping `sequence <= last_sequence` — `stream_events` in `back/app/api/v1/jobs.py`.
5. Thinking frames are not JobEvents: `nodes.publish_thinking` publishes Redis-only `event_type=thinking` with no `sequence`; SSE emits them via `_sse_live` (no `id:`) and must not advance `last_sequence`. Never fake a sequence; never put reasoning into `public_message`.
6. `JobEvent.node_id` = the node that wrote it (`runner` sets `ctx.state["_current_node_id"]`; `async_polling` uses `task.node_id`). Don't infer from `event_type` — `PROGRESS` comes from many nodes.
7. Submit order: `quote_for` + reserve inside `submit()`'s transaction → `commit` → `dispatch.enqueue_or_fail` (on broker failure: `FAILED`, `settle_release(reason="enqueue_failed")`, `ENQUEUE_FAILED` event). A new paying surface must use it; only non-reserving paths (admin sandbox, admin `requeue`) call `tasks.dispatch_generation` directly. Submission is `Idempotency-Key`-guarded.
8. Cancel is a request: `request_cancel` stamps `cancel_requested_at`; if `should_honor_immediately` (`CREATED`/`AWAITING_INPUT`, or `SUBMITTED`/`RUNNING` parked on an `AsyncProviderTask`) → `honor_user_cancel`, else `ack_cancel_request` and the runner honors it at the next node boundary. All cancel paths (API, runner, poller, input sweeper, admin) end in `honor_user_cancel`; upstream cancel only via `async_tasks.cancel_upstream`.
9. Async providers: `submit()` returns `pending=True` → runner writes an `AsyncProviderTask` checkpoint and exits with job still `RUNNING` (not terminal, not settleable). `poll()` does one check per tick (Beat every `POLL_INTERVAL_SECONDS`=15), never a loop. Liveness = renewable `deadline_at` lease (`TASK_TIMEOUT_SECONDS`=480), not worker age. `claim_due` wins `claimed_at` by conditional UPDATE (`CLAIM_LEASE` 5 min) — losing means skip, else double resume + double settle.
10. `poll_once` gives up after `MAX_POLL_DURATION_SECONDS` (2h from `created_at`): closes attempt `FAILED`, fails job `PROVIDER_TIMEOUT`, releases credits. `expire_stale_jobs` (`STALE_JOB_TIMEOUT` 30 min) deliberately skips jobs with a live async task.
11. Worker, poller and Beat must all run. Poller consumes only `provider_task_polling` with `-n zaolang-poller@%h` (never share a node name with `zaolang-worker@%h`).
12. `dispatch_generation` routing: video ops → `run_video_generation` (600s); `audio_generation` and `music_generation` → `run_audio_generation`/`run_music_generation` (360s, both on queue `audio_generation`); `video_analysis` → `run_video_analysis` (900s); everything else → `run_generation` via `image_generation_time_limits` (720s + 240s per extra character view, cap `_IMAGE_GENERATION_CAP` 960s). Every `time_limit` must stay under `broker_transport_options.visibility_timeout` (1800s) or `acks_late` re-delivers mid-flight.
13. A `bind=True` task never calls another bound task directly — share the undecorated `_run_generation_task`.
14. Terminal reactions hook `completion.on_job_terminal` (run by `transition` in the caller's transaction). Each reaction runs in its own savepoint (`session.begin_nested()` — a failed SELECT would otherwise abort the job's transaction), logs to `SystemLog` and swallows — never fail a settled job. Only reaction today: canvas landing.
15. Fast retry: `POST …/retry` resubmits `request_json` verbatim; `fast_retry.build_seed` starts at the graph's single `route_score` node only if the original failed with `PROVIDER_TEMPORARY_FAILURE`/`PROVIDER_INVALID_RESPONSE`/`PROVIDER_TASK_FAILED`, has a real `ProviderAttempt(FAILED)`, is a text/image or video operation, and has no asset axis. Seed = resolved prompt from the `GENERATING` event + `ctx.state["tried_providers"]`.
16. `image_to_image` → `text_to_image` and `image_to_video`/`video_to_video` → `text_to_video` share one template family per asset kind (`canonical_operation`); `GenerationJob.operation` keeps the real op. A reference image is optional for `image_to_image` (`nodes._REFERENCE_REQUIRED`) — don't add a check.
17. `ensure_default_templates` never re-seeds an existing active `(operation, asset_kind)` template; changing `defaults.py` needs a data migration to patch live `graph_json`.
18. Sandbox (`origin=sandbox`) is a real job, not `dry_run`: same pipeline/SSE/quality, no ledger/Draft/Work, hidden from consumer list and `get_owned_job`; `graph_override_json` runs an unpublished graph. `WorkflowContext.dry_run` is for unit tests only.
19. `MediaGenerationKind` is a hard routing filter: an `edit` video model is excluded without a video source (`edit_model_requires_video_source`) and from 白膜 motion guides (`zaolang-blocking-studio`); `/generation-jobs/models` hides it for `text_to_video`/`image_to_video`.
20. Route/generate nodes stamp `requested_resolution` / `adapted_resolution` / `adapted_vendor_resolution` / `resolution_adapt_kind` (`nodes._resolution_adapt_fields`). Keep them; pricing reads the adapted tier.
21. `draft_id` groups refine attempts into a flat version history; `submit()` advances `Draft.latest_job_id` for create/retry/promote alike (`_point_draft_at_job`) — never per-route. Pointer rules: see `zaolang-data-model`.
22. Video analysis (`Operation.VIDEO_ANALYSIS`): flag `video_analysis_enabled` gates `POST /generation-jobs`; clip = upload purpose `video_analysis_source` (≤3 min); graph `defaults.video_analysis_graph`; no output asset — result in `GenerationJob.analysis_result_json` → `GenerationJobResponse.analysis`. Synchronous provider call; a `pending` reply is treated as failure/retry.

## Recipes

**Add a job status**: `JobStatus` → in/out edges in `JOB_TRANSITIONS` (terminal → empty set + `TERMINAL_JOB_STATUSES` + settlement) → frontend status types + trilingual copy (`zaolang-i18n-region`) → run state-machine tests.

**Add a JobEvent type**: `JobEventType` → `append_event` in the node executor (`public_message` user-safe: no provider names/internal errors) → map it in `front/src/components/job/job-stages.ts`.

**Add a queue**: append to `QUEUE_NAMES` + `task_routes` → Makefile `dev-worker -Q` → worker `-Q` in `infra/docker-compose.prod.yml` and `infra/docker-compose.release.yml`. Admin health reads `QUEUE_NAMES` itself.

**Add an async provider**: `submit()` → `GenerationResult(pending=True, external_task_id=…)`; `poll()` = one status check. Nothing else: `execute_provider_generate` checkpoints, `poll_once` heartbeats/resumes/times out.

**Derived resubmission (retry/promote-like)**: model it as a plain `jobs_service.submit()` with its own preconditions and a nullable lineage column (`retry_of_job_id`, `promoted_from_job_id`) — no new status or pending state.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_job_state_machine.py tests/unit/test_async_provider_tasks.py tests/unit/test_fast_retry.py tests/unit/test_job_thinking_live.py tests/unit/test_stale_cleanup.py -v
cd back && conda run -n zaolang pytest tests/integration/test_generation_lifecycle.py tests/integration/test_job_stream.py tests/integration/test_job_retry.py tests/integration/test_job_promote.py tests/integration/test_workflow_dry_run.py tests/integration/test_generation_models_endpoint.py tests/integration/test_canvas_landing.py -v
cd back && conda run -n zaolang pytest tests/unit/test_workflow_engine.py tests/unit/test_workflow_templates_service.py tests/unit/test_asset_planning.py tests/unit/test_jobs_asset_kind.py tests/unit/test_generation_job_create_validation.py tests/concurrency/test_idempotency_and_callbacks.py -v
```

Manual: `make dev`, submit a preview-tier job; a reconnected stream must lose and duplicate no events.

## References

- `reference-asset-pipeline.md` — read when touching asset kinds (character/scene/cover, video kinds), character views and the per-view loop, default graph shapes/nodes, write-back to character/scene skills, or the video-analysis graph.
