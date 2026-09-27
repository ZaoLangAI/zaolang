# Canvas — change feed, Agent, landing, workbench reference

## Change feed (`graph_service` + `api/v1/canvas.py`)

1. Write path: `POST /v1/canvas-projects/{id}/graph-ops` is the only graph writer from the browser; `PATCH /canvas-projects/{id}` writes project metadata only; `POST /v1/canvas-agent-tasks/{id}/restore-card` re-inserts one agent card.
2. Catch-up: every `/graph-ops` response carries the changes the client missed since `base_seq` (`changes_since`), so a dropped stream is not an error — the UI shows a dot, not a banner.
3. Stream: `GET …/events` backfills from `Last-Event-ID`, emits `event: synced` (no `id:`), then live frames from Redis (`subscribe_canvas`). Client: `use-canvas-events.ts` (streamed `fetch`, `last-event-id` header, backoff).
4. `GET …/changes?since=N` is the polling read; `gap: true` → reload the project.
5. Client sync: `use-canvas-sync.ts` is a single-flight FIFO autosave; `diffGraph` (documents → ops) and `applyChanges` (feed → document) live in `graph-ops.ts`.

## Agent (plan → price → confirm)

1. `POST …/agent-runs` (202, SSE) plans; the run rests at `awaiting_confirm` with a quote. Only `POST /v1/canvas-agent-runs/{id}/confirm` moves credits.
2. Context walk (`upstream_context`) is breadth-first and bounded: `MAX_CONTEXT_DEPTH = 3`, `MAX_CONTEXT_NODES = 12`, `MAX_CONTEXT_TEXT = 600`. `MAX_TASKS_PER_RUN = 4`.
3. `_sanitise_plan` enforces what the prompt only asks: drop ops outside `PLANNABLE_OPERATIONS`; strip reference ids not in the context digest; drop (don't rewrite) an `image_to_image` left with no reference; quality tier may only move down; `forced_model` is never read.
4. `canvas_planner.FALLBACK` is an empty plan → run fails visibly at zero cost. Never invent work on parse failure.
5. Refuse before charging: node room (`MAX_NODES`) and reference checks run at plan time.
6. Confirm is a conditional transition: `_set_run_status` puts legal source states in the WHERE; task jobs use `idempotency_key=f"canvas-agent:{task.id}"`, so a double tap reserves once.
7. Camera vocabulary (`canvas-camera.ts`) reaches models as prompt text, never as params.

## Landing (`agent_service.land_job_result`)

1. Called from `completion.on_job_terminal` inside a savepoint; hook semantics (every terminal write, failure isolated to `SystemLog`) → `zaolang-generation-jobs`.
2. Success: claim the task with conditional UPDATE (`result_node_id IS NULL AND status != 'landed'`) *before* `insert_agent_node`, so a redelivered terminal cannot create two cards. Card/binding kind is video for `text_to_video`/`image_to_video`, else image.
3. Failed/cancelled job → task status change (no card) so the placeholder shows an error.
4. `_run_outcome`: all landed → `succeeded`; none → `failed`; mixed → `partial`.
5. 「放回画布」 (`restore_task_card`) refuses while the result card still exists.

## Workbench, prompt library, workflows

1. `workbench-panel.tsx` opens one job stream at a time (expanded task only); list status arrives via the canvas stream (`agentRevision` in `use-canvas-sync.ts`).
2. Stage/outputs derivation is shared: `jobStageState` in `front/src/components/job/job-stage-state.ts`, `jobOutputs` in `front/src/components/job/job-outputs.ts` (reads both `output_url` and `output_urls`). Don't fork copies.
3. Skill cards come only from `prompt-library-panel.tsx` (click, or drag via `CANVAS_DRAG_MIME` in `canvas-dnd.ts`); a blank `skill` kind is deliberately not in the toolbar's `ADDABLE_KINDS`.
4. Placing a bound card must call `onSnapshotStale` (flush, then re-read snapshot) or it renders as 已失效 until reload.
5. Still-image catalog exception: `CANVAS_STILL_KEY_PREFIXES` in `back/app/domain/skill_library/catalog.py` — lens/scene recipes are otherwise video-only.
6. A workflow is a `CreationSkill` whose params carry a `variables` list (question model from `back/app/agents/questions.py`); `variables_of`/`has_variables` in `back/app/domain/skill_library/variables.py`. No new tables.
7. `variables` must never reach a provider: `folding.RESERVED_TEMPLATE_KEYS` strips it in `foldable_params`. Don't whitelist `TEMPLATE_FOLD_KEYS` instead.
8. Answers are appended as `问题：答案` (`workflow_service.compose_prompt`), never templated; `GenerationParams` gains nothing.
9. A workflow run is a `CanvasAgentRun` with `origin=workflow` → same confirm/cancel/landing/workbench path. Operation comes from the skill's `applicable_operations_json` (`_operation_for`); request carries `skill_ids`, not a recipe copy.
10. Paid, locked skill: detail withholds `params` but summary `has_variables` stays true → `workflow-panel.tsx` offers unlock instead of an empty form.
11. Panorama director (`director-dialog.tsx`, `panorama-viewer.tsx`) lazy-imports `@photo-sphere-viewer/core`; keep it dynamic (bundle budget → `zaolang-frontend-ui`).
