---
name: zaolang-canvas
description: Infinite canvas — CanvasProject/Node/Edge/Change rows, per-node CAS via /graph-ops, the canvas SSE change feed, domain bindings + stale degradation, canvas Agent (canvas_planner), workflow runs, workbench. Use when editing back/app/domain/canvas, api/v1/canvas.py or front/src/features/canvas.
---

# Infinite Canvas

**Scope**: spatial creation surface. Drama mode (`CanvasProject.series_id` set, one canvas per series via `uq_canvas_projects_series`) binds cards to domain objects; free sandbox (`series_id` NULL) is owner-only. Gated on flag `canvas_studio_enabled`; off → 404.
Not here → `zaolang-generation-jobs` (terminal-job hook, job SSE), `zaolang-data-model` (ID prefixes, transition tables, migrations), `zaolang-api-contract` (envelope, rate limits), `zaolang-editor-drama` (drama entry), `zaolang-creation-library` (skills).

## Key Paths

| Path | What |
|---|---|
| `back/app/models/canvas.py` | six tables: project `cnv`, node `cnd`, edge `cne`, change `ccg`, agent run `car`, agent task `cat` |
| `back/app/models/enums.py` | `CanvasNodeKind`, `CanvasAgentRunStatus` + `CANVAS_AGENT_RUN_TRANSITIONS`, `CanvasAgentTaskStatus`, `CanvasAgentRunOrigin` |
| `back/app/domain/canvas/graph_service.py` | `apply_ops`, `insert_agent_node`, `_next_seq`, `changes_since`, `publish_changes`, caps `MAX_*` |
| `back/app/domain/canvas/service.py` | project CRUD, `_require_flag`, `_accessible_project`, `domain_snapshot` (hydration), `_bound_skills` |
| `back/app/domain/canvas/agent_service.py` | Agent: context walk, `_sanitise_plan`, `confirm_run`/`cancel_run`, `land_job_result`, `restore_task_card` |
| `back/app/domain/canvas/workflow_service.py` | creation workflows: skill `variables` form → priced `CanvasAgentRun(origin=workflow)` |
| `back/app/agents/canvas_planner.py` | planner prompt, `PLANNABLE_OPERATIONS`, empty `FALLBACK` |
| `back/app/api/v1/canvas.py` | `/v1/canvas-projects*` (graph-ops, changes, events, agent-runs, workflow-runs), `/v1/canvas-agent-*`, drama resolve-or-create |
| `back/app/realtime/publisher.py` | `channel_for_canvas` / `publish_canvas_change` / `subscribe_canvas` |
| `front/src/features/canvas/` | UI: `canvas-view.tsx` (`@xyflow/react`), `graph-ops.ts`, `graph-convert.ts`, `use-canvas-sync.ts`, `use-canvas-events.ts`, panels |
| `front/src/app/[locale]/(studio)/canvas/[canvasId]/page.tsx` | canvas route → `CanvasShell` (md-width gate; auth via `(studio)` layout) |
| `front/src/app/[locale]/(site)/create/tools/canvas/page.tsx` | 「我的画布」 library (`CanvasLibrary`) |
| `back/tests/concurrency/test_canvas_races.py` | acceptance test: client ops + agent landing interleaved, no lost write |
| `front/e2e/flows/canvas.spec.ts` | Playwright flows |

## Invariants

1. Server never UPDATEs a node, only INSERTs (`insert_agent_node`, no `expected_revision`). Agent live state lives on `CanvasAgentRun`/`CanvasAgentTask`, never in `CanvasNode.data_json`.
2. CAS is per node, conflicts per op: each `/graph-ops` op carries `expected_revision`; stale ops return in `conflicts`, the rest commit, response 200 (not `RevisionConflict`). `graph_service.apply_ops`
3. `CanvasProject.change_seq` orders writes (allocated under row lock by `_next_seq`), never rejects one.
4. Every write appends a `CanvasChange`; deleting a node must log its cascaded edges itself (Postgres CASCADE writes no change rows). `graph_service._delete_node`
5. One SSE stream per open canvas (`GET …/events`), never one per job — `MAX_CONCURRENT_STREAMS_PER_USER = 8` in `back/app/api/sse_quota.py`. Resume via `Last-Event-ID`; backfill ends with an id-less `synced` frame.
6. Publish only after commit, from frames serialised before it. `/graph-ops` calls `publish_changes` in the route; the Agent uses `agent_service._queue_frames` (`after_commit` listener). A new write path must pick one deliberately.
7. `changes_since` → `gap: true` (cursor too old or > `MAX_CHANGES_PER_READ = 500` behind) means full reload, never "no news".
8. Canvas is never a second write path for domain objects; "送进剧集" stays explicit (`onSendToSeries` in `canvas-properties.tsx`). A prompt card no longer hands off to an image studio (AC-8 removed 用这段提示词生成); images on the canvas come from the Agent.
9. Bindings degrade to stale, never delete (scene keyed by heading, shot by `{heading}#{ordinal}`). Never persist presigned URLs — store `binding.asset_id`; `domain_snapshot` signs per request and checks asset owner ∈ owner + active collaborators.
10. `binding_asset_id` / `binding_skill_id` are indexed columns (no FK), written as a set so a swapped binding clears the old one. Card `skill_id` is client-written → `_bound_skills` filters to published-or-own.
11. Edge handles are `""`, never NULL (else `uq_canvas_edges_endpoints` is defeated); edges have no `revision`; duplicate create = applied.
12. Positions are integers; `diffGraph` rounds and diffs against the last *acknowledged* graph. `revision`/`origin` must survive `graphToFlow`→`flowToGraph` or every update conflicts.
13. Undo/redo history is client-only (`use-canvas-editing.ts`); each step persists as a normal `/graph-ops` save. Autosave coalesces — edits netting to the saved board send nothing, so e2e waits on the POST, not the 已保存 flash.
14. Caps `MAX_NODES = 2000`, `MAX_EDGES = 4000`, `MAX_OPS_PER_BATCH = 200`; an Agent plan that would overflow is refused before credits are spent.
15. Access: drama → `editor_service._accessible_series` (owner or active co-creator); free → owner; delete → owner only; inaccessible → 404.
16. The Agent never calls a provider: `confirm_run` → `jobs_service.submit` returns jobs; the route `dispatch.enqueue_or_fail`s them after commit. Only the run's author may confirm/cancel (others 404).
17. Terminal jobs land via `completion.on_job_terminal` → `land_job_result` — hook rules: see `zaolang-generation-jobs` › terminal-job hook.
18. Every canvas route declares a bucket by cost (module docstring): `confirm` → `generation_submit`, planning → `script_studio_write`, `/graph-ops` + restore-card → `editor_write`, other writes `authenticated_write`, reads `public_read`. `test_rate_limits.py` walks the router; an unbucketed route fails.
19. Only `confirm` moves credits, so only it takes `Idempotency-Key` (`CONFIRM_AGENT_RUN_ENDPOINT`): a keyed retry, even one racing the in-flight original, replays the stored response; unkeyed, a second confirm is 422. Planning/workflow-runs only quote. Front: `useConfirmCanvasAgentRun` holds one key per attempt.
20. Import (`canvas-io.ts`) is a copy: fresh node/edge ids, domain bindings dropped.
21. Removed: AGPL-derived canvas code — don't restore (repo is Apache-2.0; see `zaolang-ci-release`).

## Recipes

**Add a node kind**: add to `CanvasNodeKind` (backend enum and the hand-written union in `front/src/features/canvas/api.ts`) → render in `canvas-node.tsx` / `canvas-properties.tsx` → map in `graph-convert.ts` → i18n keys → `npm run check:messages`. No migration (kind is a string column).

**Add a graph write path**: go through `graph_service` helpers (`_next_seq`, `_log`) → publish after commit (inv. 6) → cover in `test_canvas_races.py` style.

**Add an Agent-plannable operation**: add to `canvas_planner.PLANNABLE_OPERATIONS` → handle references/tier in `_sanitise_plan` → landing card kind in `land_job_result`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_canvas_projects.py tests/integration/test_canvas_graph_ops.py tests/integration/test_canvas_events.py tests/integration/test_canvas_agent.py tests/integration/test_canvas_landing.py tests/integration/test_canvas_prompt_library.py tests/integration/test_canvas_workflow_runs.py tests/integration/test_rate_limits.py tests/unit/test_skill_context.py tests/unit/test_backfill_canvas_rows.py tests/concurrency/test_canvas_races.py -q
cd front && npm run test -- src/features/canvas && npm run check:messages
cd front && npx playwright test e2e/flows/canvas.spec.ts --project=e2e   # prereqs: zaolang-testing-qa
```
Manual: open one canvas in two windows; a card added in one appears in the other (header dot = stream attached).

## References

- `reference-canvas.md` — read when touching the change feed, Agent planning/confirm, result landing, workbench, prompt library or workflow runs.
