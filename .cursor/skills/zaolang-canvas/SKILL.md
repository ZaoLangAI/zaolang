---
name: zaolang-canvas
description: Infinite canvas — CanvasProject / CanvasNode / CanvasEdge / CanvasChange row storage, per-node compare-and-set, the `/graph-ops` batch write path, the canvas-scoped SSE change stream, domain bindings and their stale degradation, the batched hydration snapshot, the generation workbench, the prompt library and creation workflows. Use when changing the canvas surface, its persistence, its concurrency model, its live updates, or anything that writes cards onto it.
disable-model-invocation: true
---

# Infinite Canvas

## Scope

A spatial second way to create, alongside the linear `/create/short → /create/script → /studio-editor` path. Two modes, distinguished **solely** by whether `CanvasProject.series_id` is set:

- **Drama mode** (`series_id` set) — cards bind to real domain objects (`DramaEpisode`, a script breakpoint, a `CreationSkill`, a `Draft`, a `Work`). The canvas and `/create/short`'s dashboard are two views of one truth. One canvas per series, enforced by a partial unique index.
- **Free sandbox** (`series_id` NULL) — standalone image / video / prompt / note cards. Strictly personal; a collaborator never sees them.

Feature-flagged on `canvas_studio_enabled`. Off means 404, not 403.

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/models/enums.py` | the canvas enum family: `CanvasNodeKind` (10 values), `CanvasNodeOrigin`, `CanvasChangeEntity`, `CanvasChangeAction`, `CanvasAgentRunOrigin`, and a **second job-style state machine** — `CanvasAgentRunStatus` + `CANVAS_AGENT_RUN_TRANSITIONS` + `TERMINAL_CANVAS_AGENT_RUN_STATUSES`, plus `CanvasAgentTaskStatus` + `TERMINAL_CANVAS_AGENT_TASK_STATUSES`. It is parallel to `JOB_TRANSITIONS`, not derived from it: adding a status to one does not touch the other |
| `back/app/models/canvas.py` | six tables: `CanvasProject` (`cnv_`), `CanvasNode` (`cnd_`), `CanvasEdge` (`cne_`), `CanvasChange` (`ccg_`), `CanvasAgentRun` (`car_`), `CanvasAgentTask` (`cat_`) |
| `back/app/domain/canvas/graph_service.py` | The three concurrency rules, `apply_ops`, `insert_agent_node`, `_next_seq`, `changes_since`, caps |
| `back/app/domain/canvas/service.py` | Project CRUD, `_accessible_project`, `_require_flag`, `domain_snapshot`. The whole surface is gated on `CANVAS_STUDIO_FLAG = "canvas_studio_enabled"` (`platform_config/schemas.py`, labelled in `api/v1/admin/config.py`, surfaced as `Me.features.canvas_studio`, turned on locally by `make seed`) and a disabled flag raises `NotFound`, not `Forbidden` — an off feature does not advertise itself |
| `back/app/api/v1/canvas.py` | Routes: `GET`/`POST /v1/canvas-projects`, `GET`/`PATCH`/`DELETE /v1/canvas-projects/{id}`, `…/graph-ops`, `…/changes`, `…/events`, `…/agent-runs` (`POST` 202 SSE + `GET` list), `…/workflow-runs`, `GET /v1/canvas-agent-runs/{run_id}` + `…/confirm` + `…/cancel`, `POST /v1/canvas-agent-tasks/{task_id}/restore-card`, and `GET /v1/drama-series/{series_id}/canvas` (resolve-or-create, the drama entry point — see `zaolang-editor-drama`). `POST /graph-ops` is the only path that writes the **graph** (`PATCH /canvas-projects/{id}` writes project metadata; `restore-card` re-inserts one agent-produced card through the same change feed); `GET /events` is the change stream. **No route here declares a rate-limit bucket or accepts an `Idempotency-Key`** — including `confirm`, which spends credits; that is a known divergence from `zaolang-api-contract` invariant #5, not a pattern to copy |
| `back/app/realtime/publisher.py` | `channel_for_canvas` / `publish_canvas_change` / `subscribe_canvas` |
| `front/src/features/canvas/use-canvas-events.ts` | The client half of the stream — `fetch` with a streamed body, `Last-Event-ID` resume, backoff |
| `back/alembic/versions/20260903_0900_add_canvas_projects.py` | All six tables in one revision (`a7f2c4d9e310`, on `c4d8e1f2a6b0`) |
| `front/src/features/canvas/graph-ops.ts` | `diffGraph` (documents → operations), `applyChanges` (feed → document) |
| `front/src/features/canvas/use-canvas-sync.ts` | Single-flight FIFO autosave against the ops API |
| `front/src/features/canvas/graph-convert.ts` | `graphToFlow` / `flowToGraph`, `missingDomainNodes`, `upstreamAssetIds`, stale-binding resolution |
| `front/src/features/canvas/canvas-view.tsx` | The `@xyflow/react` surface. It reaches a consumer route through `front/src/app/[locale]/(studio)/canvas/[canvasId]/page.tsx` (chrome-less, `StudioAuthGate`, `md`-width gate in `canvas-shell.tsx` — no Chrome/Edge requirement, unlike the editor) and the library card at `front/src/app/[locale]/(site)/create/tools/canvas/page.tsx` |
| `front/src/features/canvas/` (rest) | `canvas-shell.tsx` (the shell + width gate), `canvas-library.tsx` (「我的画布」), `canvas-node.tsx` / `canvas-properties.tsx` / `canvas-toolbar.tsx` / `canvas-context-menu.tsx`, `canvas-io.ts` (import/export), `api.ts` / `agent-api.ts` (the two HTTP clients), `use-canvas-agent.ts`, `workflow-panel.tsx`, `send-to-series.tsx` (stamps `linkEpisodeId` on a generation), `camera-control.tsx`, and the panorama director — `director-capture.ts` / `director-dialog.tsx` / `panorama-viewer.tsx`, which lazily imports `@photo-sphere-viewer/core` + `three` so the ~626KB chunk is paid only by someone who opens it (see `zaolang-frontend-ui`'s bundle budget) |
| `front/src/features/canvas/canvas-camera.ts` | Camera-direction vocabulary — reaches models as prompt text, never as parameters |
| `back/app/domain/canvas/agent_service.py` | Context walk, plan sanitising, confirm/cancel — where the Agent's guardrails are actually enforced |
| `back/app/agents/canvas_planner.py` | The planner prompt, its empty `FALLBACK`, and the JSON parse |
| `back/app/domain/jobs/dispatch.py` | `enqueue_or_fail`, shared by the studios and the Agent |
| `back/app/domain/jobs/completion.py` | `on_job_terminal` — the one place anything reacts to a job finishing |
| `front/src/features/canvas/agent-panel.tsx` | Goal -> plan -> priced review -> confirm |
| `front/src/features/canvas/workbench-panel.tsx` | Run -> task list; one live job stream at a time |
| `front/src/components/job/job-stage-state.ts` | Stage derivation, shared by four job UIs |
| `front/src/components/job/job-outputs.ts` | `output_url` vs `output_urls` — one reader for both |
| `front/src/features/canvas/prompt-library-panel.tsx` | Skill browser; click or drag to place a card |
| `front/src/features/canvas/canvas-dnd.ts` | The custom drag MIME and its validating reader |
| `back/app/domain/canvas/workflow_service.py` | Creation workflows — variable form -> priced run |
| `back/app/domain/skill_library/folding.py` | `foldable_params` / `flat_template_params` / `fold_params_prompt` |
| `back/app/domain/skill_library/variables.py` | `variables_of` / `has_variables` — is this skill a workflow |
| `back/tests/concurrency/test_canvas_races.py` | The acceptance test for the persistence design |
| `back/app/scripts/seed.py` | **Not** wired up: none of the six canvas tables is in `RESET_TABLES`, so `make seed --reset` clears them only transitively (`TRUNCATE users CASCADE`, and the drama `DELETE` for a series-bound canvas). A free-standing canvas owned by a surviving user therefore outlives a reseed — known gap, see `zaolang-data-model`'s "Add a table" |

## Invariants

1. **The server never UPDATEs a node — it only INSERTs.** An Agent result becomes a *new* card and a *new* edge (`insert_agent_node`). An INSERT carries no `expected_revision`, so a generation finishing at an arbitrary moment cannot collide with whatever the browser is doing. This is the rule the whole design rests on.

2. **Corollary of #1: an Agent's live state must never live in `CanvasNode.data_json`.** Putting it there gives client and server one cell to write again. It belongs on `CanvasAgentRun` / `CanvasAgentTask`, joined by id.

3. **Compare-and-set is per node, and conflicts are per operation.** Each op in a `/graph-ops` batch carries its own `expected_revision`. A stale op is reported in `conflicts` and **the rest of the batch still commits**; the response is 200, not 409. This is a deliberate break from `RevisionConflict` elsewhere in the codebase — rolling twenty accepted drags back because a twenty-first card moved under one of them loses real work and protects nothing.

4. **`CanvasProject.change_seq` is a lock, not a token.** Allocated by `_next_seq` under the project row's lock via `UPDATE ... RETURNING`. It *orders* writes and never rejects one — that is exactly how it differs from the `revision` column it replaced, which made two writers contend for one number and rejected the loser.

5. **Every write appends to `canvas_changes`.** A deleted row cannot carry its own tombstone, so without the feed a client that missed a delete would render a card the server no longer has, forever.

6. **Deleting a node must log its cascaded edges explicitly.** Both `canvas_edges` endpoints are `ondelete=CASCADE`, and **Postgres will not write those change rows for you**. `_delete_node` selects the attached edges, deletes them, and logs each — otherwise a `?since=N` client keeps drawing lines into a card that is gone.

7. **One stream per open canvas, never one per generation in flight.** `sse_quota.MAX_CONCURRENT_STREAMS_PER_USER` is 8, so fanning out over `GET /generation-jobs/{id}/events` would let a four-task Agent run in two tabs consume a user's entire budget and starve their notification stream. The canvas stream also multiplexes card, edge and (later) agent-run frames, which is what makes multi-tab and co-creator convergence one code path instead of several.

8. **Publish only after commit, from frames serialised before it.** ORM rows expire on commit, so the payloads are built first; announcing a write from inside the transaction would have other windows render a card the database can still roll back.

9. **The backfill ends with an explicit `synced` frame.** Without it a client cannot distinguish "caught up, now live" from "still replaying" — which matters both for what the UI shows and because applying live frames part-way through a replay can apply them out of order. It carries no `id:`: it is a position the client already holds, not a change to resume from.

10. **A dropped stream is not an error state.** Every write carries its own catch-up read, so a disconnected canvas stays correct — it just stops learning about other windows. The UI says so with a dot, not a banner.

11. **`gap: true` means reload, never "no news".** `changes_since` reports a gap when the cursor predates what the feed can reconstruct, or when the client is more than `MAX_CHANGES_PER_READ = 500` frames behind. Handing back a partial history the client would apply as if complete is the one failure mode worse than a full reload.

12. **The canvas never becomes a second write path for domain objects.** Episodes, scripts and drafts keep their own routes. The canvas owns *its own* content (including agent-generated cards) — a different thing from owning the domain. A generated card is not an `EpisodeContentLink`; "送进剧集" stays the explicit user action in `send-to-series.tsx`.

13. **Bindings are best-effort and degrade to stale, never to deleted.** The domain has no stable ids for scenes or shots — a scene is keyed by its heading string, a shot by `{heading}#{ordinal}` (`front/src/features/script/script-breakpoint.ts`) — so any script revision that renames or reorders scenes can orphan a binding. The card stays, marked stale.

14. **A presigned URL is never persisted in a card.** Cards store `binding.asset_id`; `domain_snapshot` resolves signed URLs per request. Persisting one gives a canvas that renders for an hour and shows broken images forever.

15. **Asset resolution re-checks ownership against owner *and active collaborators*.** `register_generated_asset` stamps `owner_user_id = job.user_id`, so on a shared drama canvas a co-creator's generated image belongs to them. Filtering on the project owner alone renders every collaborator-generated card broken.

16. **`binding_asset_id` is a column, not a JSON lookup.** It is the one binding field read by a query rather than the renderer; leaving it inside JSONB forces a Python scan of the whole canvas on every hydration.

17. **Edge handles are the empty string, never NULL.** Postgres treats NULLs as distinct inside a unique constraint, so nullable handles would let the identical edge insert twice and silently defeat `uq_canvas_edges_endpoints`.

18. **Edges have no `revision` and need none.** They carry no mutable payload: creating one twice is caught by the endpoint constraint (and reports as *applied*, so a retried flush cannot fail), and deleting a missing one is a no-op success.

19. **Positions are integers.** Matching this schema's no-floats rule, and keeping the equality comparisons on the CAS path exact. `diffGraph` rounds before comparing, so a sub-pixel tremor costs no round trip.

20. **`revision` and `origin` must survive the React Flow round trip.** Every commit goes `graphToFlow` → user edits → `flowToGraph`. Dropping `revision` in `CanvasNodeData` makes every update quote `0` and come back a conflict.

21. **The client diffs against the last *acknowledged* state, not the previous local one.** That is what collapses "add a card, then drag it four times" into one create at the final position.

22. **Undo/redo is client-side only.** `use-canvas-editing.ts` owns it. Do not build server-side undo.

23. **Caps are enforced before credits are spent.** `MAX_NODES = 2000`, `MAX_EDGES = 4000`, `MAX_OPS_PER_BATCH = 200`. An Agent plan that would overflow the canvas must be refused at plan time — a job that succeeds, captures credits, and then cannot land its card is the worst available outcome.

24. **Access follows the mode.** Drama-mode canvases use `editor_service._accessible_series` (owner or active co-creator, matching episode/script CRUD). Free canvases are owner-only. Deleting a canvas is owner-only in both modes. An inaccessible canvas 404s rather than 403s, so its existence is not confirmed.

## The workbench, the prompt library, and workflows

38. **The workbench opens one job stream at a time.** Expanding a task connects it; collapsing disconnects. This is invariant #7 applied to the panel: a stream per task would spend the very quota the canvas-scoped stream exists to protect. List-level status still arrives on the canvas stream, via `useCanvasSync`'s `agentRevision`.

39. **Stage derivation lives in exactly one function.** `jobStageState` — the "furthest reached" set, the displayed stage, the awaiting-input park, the terminal fallback. It was copied verbatim in three components before the workbench needed a fourth, and the subtleties are exactly the kind that drift apart across copies. Same for `jobOutputs`: a job reports a single result on `output_url`, so a reader that consults only `output_urls` shows nothing for almost every job.

40. **"放回画布" only re-lands a card the user deleted.** Results place themselves (invariant #34). `restore_task_card` refuses when the card is still there, so a double-tap cannot leave two cards for one paid generation.

41. **A skill card's `skill_id` is client-written and must be access-checked on read.** Unlike the episode-derived ids `_hydrate_skills` resolves, a node binding is whatever the browser put there. `_bound_skills` applies the bulk form of `get_usable` — published to anyone, a draft only to its owner — so pasting a stranger's unpublished skill id into a card cannot leak its title back. Visibility, not entitlement: a locked paid skill still shows a card, and `assert_unlocked_for_use` is what gates running it.

42. **`binding_skill_id` is a column, for the same reason as #16**, and the denormalised binding columns are written as a *set*: a binding swapped from a skill to an asset must not leave the old column behind, still hydrating a skill the card no longer points at.

43a. **Placing a bound card must re-read the snapshot.** Hydration decides `stale` from `snapshot.skills` / `snapshot.assets`, and the snapshot in hand predates the card the user just placed — so without `onSnapshotStale` a freshly picked skill renders as 已失效 until the next full page load. Same callback the upload and director-capture paths use, and it flushes before re-reading so a GET cannot overtake the write that carries the binding.

43b. **A paid skill's `params` come back empty until it is unlocked, but `has_variables` does not.** `CreationSkillDetail` withholds `params` from a viewer who has not unlocked the skill, so the workflow form cannot be drawn — while the summary's computed `has_variables` is still true. The panel must branch on that pair and offer the unlock, or a paid workflow claims to have no form at all.

43. **A blank `skill` card is not addable from the toolbar.** It would bind nothing and therefore render permanently stale. The prompt library is the only way one gets a skill — by click or by drag, through the shared `canvas-dnd` MIME.

44. **The canvas still section of the catalogue exists because framing is not a camera move.** Every `lens`/`scene` recipe is video-only, since a move only means something over time; the canvas composes a still first. `CANVAS_STILL_KEY_PREFIXES` (`frame-` / `light-` / `stage-` / `method-`) is the enumerated exception, and it is enumerated so relaxing the rule for framing cannot quietly relax it for `lens-oner-continuous`.

45. **A creation workflow is a `CreationSkill` with a `variables` list — zero new tables.** The list uses the agents' own question model (`app/agents/questions.py`), so `QuestionField` renders it with no second renderer to drift.

46. **`variables` must never reach a provider.** `execute_skill_context` folds a template skill's whole `params_json` into `ctx.params`, so the question list would ride straight out to the model. `folding.RESERVED_TEMPLATE_KEYS` strips it. Do **not** fix this by narrowing `TEMPLATE_FOLD_KEYS` to all skills — a user-authored template may legitimately carry `seed` or `duration_seconds`, and a whitelist would silently change what those already do.

47. **Variable substitution stays in the domain layer; `GenerationParams` gains nothing.** A variable belongs to one run, not to the skill and not to the platform's generation contract. Answers are appended as `问题：答案` rather than templated into `{id}` placeholders — a placeholder syntax would make every workflow's prompt a small language with its own escaping and failure modes.

48. **A workflow run *is* a `CanvasAgentRun`, distinguished by `origin`.** It rests at `awaiting_confirm` and goes through the same `confirm_run` / `cancel_run` / landing / workbench, so there is one execution path rather than two that drift. `origin` is a column and not `planner_agent_run_id IS NULL` — that would make a nullable pointer double as a type tag.

49. **A workflow's operation comes from the skill, not the request.** The recipe was written for one modality; letting a caller choose would submit a video job carrying a still-frame recipe. A skill declaring no operations is not runnable as a workflow.

50. **The workflow request carries `skill_ids`, not a copy of the recipe.** `execute_skill_context` folds the rest server-side, the same path a studio submission takes. Copying would fork the recipe at run time.

## The Agent

Plan, price, confirm. A run rests at `awaiting_confirm` with a quote attached, and the confirm tap is the only thing that moves credits.

25. **The Agent never calls a provider.** It emits `GenerationParams` and goes through `jobs_service.submit`, so credits, routing, moderation and `skill_context` behave exactly as they do for a hand-driven studio request. Anything else would be a second, divergent generation path.

26. **Nothing the planner says is trusted.** `_sanitise_plan` is where the rules hold: an operation outside `PLANNABLE_OPERATIONS` is dropped, a reference id absent from the context digest is stripped, an `image_to_image` left with no usable reference is dropped whole (rewriting it to text-to-image would generate something the user never asked for and charge them), the quality tier may only move *down* from the user's choice, and `forced_model` is not read at all. Stating these in the prompt makes the model cooperate; enforcing them in code is what makes them true.

27. **The planner's `FALLBACK` is an empty plan.** The direct analogue of `quality.py` defaulting to `pass`: a broken evaluator must not burn credits by retrying, and a broken planner must not spend them on invented work. An empty plan fails the run visibly at zero cost.

28. **Refuse before charging, never after.** `MAX_NODES` room and every reference check run at plan time. A job that succeeds, captures credits and then has nowhere to land its card is the worst outcome this feature can produce.

29. **The context walk is breadth-first and bounded** — depth 3, 12 cards, 600 characters each. Breadth-first so the budget is spent on the cards nearest the one selected, which are the ones the user meant.

30. **Confirmation is a conditional transition, and task idempotency keys are deterministic.** `_set_run_status` puts the legal source states in the WHERE clause, so a double-tapped confirm submits one set of jobs; `canvas-agent:{task.id}` means even a replayed submit reserves credits once.

31. **Only the run's author may confirm or cancel it.** A co-creator can watch a run on a shared canvas and start their own, but confirming spends the author's balance.

## Landing results

32. **The hook hangs off `state_machine.transition`, not `settle_success`.** Every terminal write in the system funnels through it — the pipeline, the async-polling worker, and `pipeline._fail`'s crash path — and its conditional UPDATE already guarantees only the first terminal write wins. `settle_success` was the tempting alternative and is wrong: it never runs on failure, so a task whose job failed would spin forever.

33. **A failed or cancelled job lands too.** Not as a card — as a state change on the task, so the placeholder turns into an error the user can read instead of a spinner that never stops.

34. **Landing is idempotent by conditional UPDATE.** `WHERE result_node_id IS NULL AND status != 'landed'` claims the task *before* the insert, the same `rows_affected` trick the job state machine uses on itself. A redelivered terminal must not leave two cards for one generation the user paid for once.

35. **A landing failure must never fail the job.** By the time this runs, credits are settled and the output exists. Losing a card is recoverable; turning a paid-for, finished job into a failure is not — so `on_job_terminal` isolates each reaction and records it to `SystemLog` instead.

36. **A run with some tasks landed and some failed is `partial`, not `failed`.** Calling it a failure tells the user their work is gone while it is sitting in front of them.

37. **The Agent's change frames are published from the session's own `after_commit`.** `agent_service._queue_frames` registers an `after_commit` listener, so the frames fire exactly when the transaction lands and never on a rollback — requiring each *agent* call site to remember a publish-after-commit is a rule that holds until someone adds a fourth one. **`/graph-ops` is the exception and still publishes by hand**, calling `graph_service.publish_changes` in the route after its commit; if you add a third writing path, match one of these two shapes deliberately rather than assuming the listener covers you.

## Licence

This directory is **entirely first-party**. An earlier revision adapted three files from `tigerowo/infinite-canvas` (AGPL-3.0); all three were independently rewritten or removed, because the repo root `LICENSE` is internal-proprietary and AGPL §13 would have obliged the whole service to offer its source. See `zaolang-ci-release` invariant 4 — **do not** reintroduce AGPL-derived code or add an AGPL notice here.

## Verify

```bash
cd back && pytest tests/integration/test_canvas_projects.py tests/integration/test_canvas_graph_ops.py tests/integration/test_canvas_events.py tests/integration/test_canvas_agent.py tests/integration/test_canvas_landing.py tests/integration/test_canvas_prompt_library.py tests/integration/test_canvas_workflow_runs.py tests/unit/test_skill_context.py tests/concurrency/test_canvas_races.py -q
```

`tests/concurrency/test_canvas_races.py` is the acceptance test for the persistence design: a client op batch and an agent landing, interleaved on one canvas, with neither losing a write. If that passes, the storage model is doing its job.

Frontend: `npm run test -- src/features/canvas`, then `npm run check:messages`.

Convergence is worth checking by hand once: open the same canvas in two windows, add a card in one, and it appears in the other with no reload. The header dot reports whether the stream is attached.
