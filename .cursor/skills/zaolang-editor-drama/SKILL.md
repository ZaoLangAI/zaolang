---
name: zaolang-editor-drama
description: Browser-based drama editor — the canonical timeline (integer ticks), immutable EpisodeCut revisions, single-writer leases, sequential export, editor_planner, Remote MCP, and the Series.kind / character-roster isolation. Use when working on /create/drama, EditCommand, cut revisions, editor leases, DeliveryVariant, EditorExport, bind-editor-export, editor_planner, /mcp, or Series kind=drama vs kind=cast.
disable-model-invocation: true
---

# Drama Editor

## Scope

Both the product surface and the editing engine live in this repo. The only thing exposed externally is `EditCommand` and the canonical timeline — never expose an external editor's own project/element types through the API.

## Key Paths

| Path | Contents |
| --- | --- |
| `front/src/features/editor/` | adapter ports, canonical apply, the lease session, timeline UI, sequential-export runner |
| `front/src/features/editor/from-job.ts` | the single entry point for "enter editing" from a job page — never statically pull the whole editor from the `features/editor` barrel file |
| `front/src/app/[locale]/(site)/create/drama/` | desktop Chrome/Edge gate; narrow screens get a read-only notice and are excluded from `a11y-mobile` |
| `back/app/models/editor.py` | `drama_episodes` / `episode_cuts` / `cut_revisions` / leases / variants / exports / `MediaAnalysis` |
| `back/app/models/characters.py` | `Series.kind` (`cast` \| `drama`) and production-project fields — never build a second episode table |
| `back/app/domain/editor/` | revision CAS, command validation, leases, export completion (HEAD + checksum + ffprobe), analysis enqueueing |
| `back/app/domain/characters/service.py` | `/v1/series` recognizes only `kind=cast`; a drama id 404s against the roster API |
| `back/app/api/v1/editor.py` | `/v1/drama-series`, cuts, leases, revisions, exports, `bind-editor-export`, `episode-cuts:from-job` |
| `back/app/mcp/` | a self-implemented `POST /mcp` Streamable HTTP endpoint; must use FastAPI's `DbSession` — never `session_scope()` |
| `back/app/agents/editor_planner.py` | an independent, read-only-tools planner whose result is recorded as an `AgentRun` — it never creates a fake `GenerationJob` |
| `back/app/scripts/seed.py` | `_seed_editor_flags` flips five local flags on; `_seed_editor_demo` gives `linhai` a drama project |
| `docs/editor.md` | the product path and Phase 0 scope boundary |

## Invariants

1. **Time is expressed in integer ticks**, `120000 ticks = 1s`, validated against the JS safe-integer range. Floating-point seconds are forbidden.
2. **The canonical document lives server-side**, in `cut_revisions.document_json`. MCP's `apply_edit_plan` doesn't depend on any open browser tab.
3. **MCP's `project_id` equals `Series.id`** (`kind=drama`). Don't build a new Project table — `Series` here is a reuse of the character-roster table, not a second episode model.
4. **`/v1/series` returns only `kind=cast`.** `list_series` / `_owned_series` / `create_series` all filter explicitly on `SeriesKind.CAST`. A drama id against `/v1/series/{id}` must 404 (indistinguishable from not-found — it doesn't leak the existence of a production project). "Recent series" on the create hub and in the short-video studio read the roster, not editing projects.
5. **Episode writes go through `POST /v1/drama-series` with `kind=drama`.** `from-job` can auto-create a drama series. The roster API must never write a drama row.
6. **Leases have a single writer**: conditional updates, and a terminal lease can't be reopened by a heartbeat. Losing a lease degrades to read-only rather than overwriting a newer head.
7. **A failed command batch rolls back entirely**, leaving head unchanged. Writing a revision requires `expected_revision_id` for CAS.
8. **Internal editing revisions never write a `LineageEdge`.** Publishing must bind to an explicitly successful `EditorExport.output_asset_id`; the entry point is not PublishKit.
9. **Manual editing and browser export are free.** AI planning only records an `AgentRun` and never touches ledger unique keys.
10. **Feature flags default to false**: `drama_studio_enabled` / `web_editor_enabled` / `variant_export_enabled` / `editor_ai_enabled` / `editor_mcp_enabled`. Export/AI/MCP all depend on `web_editor_enabled`; off means 404. Local `make seed` flips all five on — production defaults to off.
11. **MCP's audience is always `mcp`.** Consumer and admin tokens are rejected. There is no publish tool.
12. **Never embed an external editor's codebase wholesale into `front/`.** Rendering/export always goes through this repo's own adapters and `mediabunny`.
13. **A job page must import only `from-job.ts`.** Never `import … from '@/features/editor'` — that pulls the WASM/mediabunny bundle into the job page. `export-runner.ts` dynamically imports `mediabunny`.
14. **Analysis runs on its own queue, `media_analysis`.** Beat also owns `expire_editor_leases` / `expire_orphan_editor_uploads` (hung off `webhook_reconcile`). `make dev-worker`'s `-Q` list must include `media_analysis`.
15. **`make seed --reset` deletes empty drama shells while keeping the cast roster.** `Series` is excluded from `RESET_TABLES`; `_reset` additionally runs `DELETE FROM series WHERE kind = 'drama'`, while editor sub-tables are inside `RESET_TABLES`.

## Product Path

Generation succeeds → "Enter editing" → `/create/drama/{cutId}` → sequential export → `POST /v1/drafts/{id}/bind-editor-export` → the eight-step publish flow.

## Local Database State

Trust `alembic heads`, not a revision id cited in a doc, as current. The editor tables land in `20260814_0200_add_drama_editor.py`; later migrations include `20260814_0900_add_work_appeals_and_hide_reason.py` (`works.hide_reason` + `work_appeals`) and `20260814_1400_add_editor_lease_active_unique_index.py` (a partial unique index on active leases). Run `make migrate` after pulling. The `alembic check` noise on `agent_nodes.category` / `provider_async_tasks`'s server_default is a known pre-existing issue — don't open a new migration for it. Don't run `make reset` unless you intend to destroy the data volume.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_editor_commands.py tests/integration/test_editor.py tests/integration/test_editor_mcp.py tests/integration/test_series.py -v
make openapi-check
make messages
```

`test_series.py` must cover "`/v1/series` excludes drama, and a drama id 404s against the roster API." Phase 0 gold standard: export a 10s MP4/WebM on target Chrome/Edge, and `createIndependentEngines()` must support multiple instances. Media acceptance cannot be claimed until this has run on a real wide screen.
