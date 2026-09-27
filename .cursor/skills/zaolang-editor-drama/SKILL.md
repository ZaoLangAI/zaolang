---
name: zaolang-editor-drama
description: Short-drama production — /create/short dashboard, Series/DramaEpisode, co-creators, timeline editor (/studio-editor, EditCommand, leases, exports, MCP), 文案创作 /create/script, shortform profiles. Use when touching app.domain.editor|script_writing|shortform or features/editor|drama-dashboard|script.
---

# Drama Editor & Short-Drama Production

**Scope**: one `Series(kind=drama)` → `DramaEpisode` model backs four surfaces: the `/create/short` dashboard (`features/drama-dashboard`), 文案创作 at `/create/script` (`features/script`), the desktop timeline editor at `/studio-editor/{cutId}` (`features/editor`), and Remote MCP. Only `EditCommand` + the canonical timeline are exposed; never an external editor's own types. Also owns shortform delivery profiles (`/v1/shortform/profiles`).
Not here → `zaolang-canvas` (`/v1/drama-series/{id}/canvas`), `zaolang-blocking-studio` (`/create/script/{id}/blocking`), `zaolang-generation-jobs` (job SSE, terminal hook), `zaolang-agent-gateway` (`copy` slots, providers), `zaolang-data-model` (migrations, ID prefixes, status tables), `zaolang-platform-config` (flags), `zaolang-media-assets` (upload purposes, provenance), `zaolang-creation-library` (`/v1/characters`, `/v1/scenes`).

## Key Paths

| Path | What |
|---|---|
| `back/app/models/editor.py` | `DramaEpisode`, `EpisodeCut`, `CutRevision`, leases, `DeliveryVariant`, `EditorExport`, `MediaAnalysis`, `EpisodeContentLink`, `EpisodeScriptTurn` |
| `back/app/models/characters.py` | `Series` (kind, series-form metadata, `shortform_profile_key`) and `SeriesCollaborator` |
| `back/app/api/v1/editor.py` | the only series/episode/content-link surface (`/v1/drama-series`, `/v1/drama-episodes`) + cuts, leases, revisions, plans, variants, exports, MCP tokens |
| `back/app/domain/editor/service.py` | access resolvers, series/episode/content-link CRUD, trash/purge, preview fill, `create_cut_from_job`, revisions, variants, plans |
| `back/app/domain/editor/commands.py` | `validate_batch` + command apply; closed allowlists (effects, keyframes, tracks, markers) |
| `back/app/domain/editor/` | also `document.py`, `time.py` (ticks, caps), `leases.py`, `exports.py`, `analysis.py`, `collaborators.py`, `flags.py`, `state_machine.py` |
| `back/app/mcp/server.py` | self-implemented `POST /mcp` Streamable HTTP; `TOOLS` = tool→scope table |
| `back/app/agents/editor_planner.py` | read-only AI edit planner, streamed via `stream_plan_timeline` |
| `back/app/domain/script_writing/service.py` | 文案创作: `prepare_new_script`/`prepare_turn`, streamed draft/revise, `delete_script`, links |
| `back/app/api/v1/scripts.py` | `/v1/scripts` — SSE model turns + JSON edits, `POST /scripts/extract` |
| `back/app/domain/shortform/service.py` | delivery profiles from config (`catalog`, `resolve_profile`, `assert_params_consistent`) + `PublicationIntent` writes |
| `back/app/api/v1/shortform.py` | `GET /v1/shortform/profiles` (catalogue for the export panel) |
| `back/app/api/v1/distribution.py` | platform OAuth links, `publications:fanout`, work/series metrics (logic in `app.domain.distribution`) |
| `front/src/features/editor/` | `drama-editor.tsx` (sync queue), `engine/` (canonical, compositor, export runner), `timeline/`, `studio/` (OpenCut-adapted shell) |
| `front/src/features/editor/from-job.ts` | the only editor import allowed on job pages (`createCutFromJob`) |
| `front/src/features/editor/gate.tsx` | `EditorGate`: below `md` or non-desktop Chrome/Edge → `EmptyState`, children never mount |
| `front/src/app/[locale]/(studio)/studio-editor/[cutId]/page.tsx` | chrome-less editor route; `(site)/create/short/[cutId]` only redirects here |
| `front/src/features/drama-dashboard/` | `/create/short` library, series detail, episode panel, collaborators, trash/purge, publish + analytics |
| `front/src/features/script/` | script landing/editor/chat, breakpoints, clip studio, batch generation, link picker |
| `back/app/scripts/seed.py` | `_seed_editor_flags` turns editor/script/canvas/blocking flags on locally |
| `docs/editor.md` | product path and scope notes |

## Invariants

1. **Removed: `kind=cast` Series roster and `/v1/series` — don't restore.** `SeriesKind.CAST` stays on the enum only; every creation path passes `kind=drama`. Series/episode CRUD has exactly one route family (`back/app/api/v1/editor.py`); don't add a second mount.
2. `drama_studio_enabled` (`FLAG_DRAMA`) is not enforced on `/v1/drama-series`; series/episode/content-link CRUD is un-flagged and kind-agnostic. The timeline editor needs `web_editor_enabled`; `variant_export_enabled`/`editor_ai_enabled`/`editor_mcp_enabled` also require it; off → 404 (`back/app/domain/editor/flags.py:require_flag`).
3. Access tiers (`back/app/domain/editor/service.py`): `_accessible_series`/`_accessible_episode` (owner **or** active `SeriesCollaborator`) gate metadata, episode CRUD, content links, canonical work, script writing. `_owned_*`/`require_drama_series` (owner only) gate trash/untrash/purge, every cut/lease/revision/export/plan, and distribution. Never widen owner-only paths; mirror via `viewer_role` in the UI.
4. **from-job binding** (`create_cut_from_job`): same job twice → existing cut (`_cut_for_source_job`). Else draft `params.link_episode_id` names the episode: foreign → 4xx, deleted → cleared (`_clear_stale_link_episode_id`) and fall through. No link: `series_id` given → new episode there; else reuse the newest non-trashed drama series or mint one (`target_platforms=[manual_download]`) plus a new episode.
5. from-job is get-or-create on the primary cut (`kind=full`, name `主剪辑`, `uq_episode_cuts_episode_kind_name`, `_default_full_cut`); then `_link_job_draft_to_episode` writes a `candidate` content link and seeds `link_episode_id` if absent.
6. `_seed_draft_link_episode_id`: a draft content link writes `params.link_episode_id` only when the draft has none, so a later 进入剪辑 never mints a second series. `POST /v1/drafts` with `link_episode_id` best-effort links (`back/app/domain/publishing/service.py:_maybe_link_draft_to_episode`); `list_content_links` heals via `ensure_linked_drafts`.
7. **Job pages import only `front/src/features/editor/from-job.ts`** — never `@/features/editor` (pulls WASM/mediabunny). `export-runner.ts` loads `mediabunny` by dynamic `import()`. `EditorGate` has no read-only fallback.
8. Time is integer ticks, `TICKS_PER_SECOND = 120_000`, ≤ JS safe int (`back/app/domain/editor/time.py`); float seconds are forbidden. The canonical document lives server-side in `cut_revisions.document_json`.
9. Revisions are CAS on `expected_revision_id` (`RevisionConflict`); a failed batch rolls back fully. Leases are single-writer; terminal leases/exports never reopen on heartbeat.
10. Editor revisions never write a `LineageEdge`; publish binds only a succeeded `EditorExport.output_asset_id` via `ensure-bound-draft` or `bind-editor-export`. Manual editing/export are free; AI planning records an `AgentRun`, never a `GenerationJob` or ledger row.
11. MCP audience is always `mcp` (consumer/admin tokens rejected), no publish tool, uses FastAPI `DbSession` — never `session_scope()`. Tool list: `TOOLS` in `back/app/mcp/server.py`.
12. OpenCut (MIT) is adapted for UI shell/layout only under `front/src/features/editor/studio/` (see `THIRD_PARTY_NOTICES.md`); engine, timeline model and compositor stay ours. Don't widen.
13. Deleting an episode (`delete_episode`, `delete_script`) runs `purge_unpublished_editor_graph`; 422 only when `canonical_work_id` or an export bound to a published draft exists. No `DELETE /v1/episode-cuts/{id}`.
14. Series trash is a status flip; purge requires `TRASHED` and zero episodes (`purge_drama_series`). Both owner-only.
15. `script_studio_enabled` gates script writing independently (`_require_script_studio`); `prepare_new_script` mints its own `DramaEpisode` (and a `Series(kind=drama)` shell without `seriesId`) rather than calling `create_episode`.
16. Script SSE turns open their own `session_scope()` and must `session.rollback()` on every error path, then emit `event: error` as the last frame — the 202 header is already sent.
17. Shortform profiles live in config section `shortform` (`ShortformConfig` in `back/app/platform_config/schemas.py`), never hard-coded. A job carrying `params.shortform_profile` must match its aspect ratio and duration window (`assert_params_consistent`, called from `back/app/domain/jobs/service.py`). `create_variants` rejects unknown keys.
18. `create_publication_intent` only yields `EXPORTED`/`READY`; `SUBMITTED`/`FAILED` are set solely by `app.domain.distribution.service` via `mark_submitted`/`mark_failed`.
19. Episode roster thumbnail (`preview_asset_id`) auto-fills once (`maybe_fill_episode_preview`, failures swallowed); only `POST /v1/drama-episodes/{id}/preview:from-video` overwrites.

## Recipes

1. **Add an EditCommand**: add to `ALLOWED_TYPES` + validation/apply in `commands.py` → mirror apply in `front/src/features/editor/engine/canonical.ts` and the type in `engine/ports.ts` → mention in `editor_planner.py` prompt → optional client id if it creates elements (see reference-timeline-engine) → tests in `test_editor_commands.py` + `canonical.test.ts`.
2. **Add a series/episode field**: model in `back/app/models/characters.py` or `back/app/models/editor.py` + migration (`zaolang-data-model`) → `back/app/api/schemas/editor.py` → service → `make openapi` → `series-form-dialog.tsx` or `episode-panel.tsx` → `make messages`.
3. **Add a delivery profile**: edit config section `shortform` (admin config or defaults in `back/app/platform_config/schemas.py`); frontend picks it up from `GET /v1/shortform/profiles` (`pickDefaultProfileKey` in `front/src/features/editor/export-profile.ts`).
4. **Add an MCP tool**: append `(name, scope)` to `TOOLS`, dispatch in `server.py`, cover in `test_editor_mcp.py`. Never a publish tool.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_editor_commands.py tests/integration/test_editor.py tests/integration/test_editor_mcp.py tests/integration/test_editor_plans_and_races.py tests/integration/test_editor_export_provenance.py
cd back && conda run -n zaolang pytest tests/integration/test_series_episodes.py tests/integration/test_series_trash.py tests/integration/test_episode_preview.py tests/integration/test_drafts.py
cd back && conda run -n zaolang pytest tests/unit/test_script_writing_agent.py tests/unit/test_scripts_streaming.py tests/unit/test_script_source_extract.py tests/integration/test_scripts.py tests/unit/test_prompt_enhance.py tests/integration/test_prompts_api.py
cd back && conda run -n zaolang pytest tests/unit/test_shortform_rules.py tests/integration/test_shortform.py tests/unit/test_distribution.py tests/integration/test_distribution.py
cd front && npx vitest run src/features/editor src/features/script src/features/drama-dashboard
make openapi-check && make messages
```

## References

- `reference-timeline-engine.md` — read when changing commands, tracks/effects/keyframes/transitions/markers, the sync queue, compositor/audio, leases, exports, transcription, MCP or the AI planner.
- `reference-series-episodes.md` — read when changing series/episode CRUD, content links, canonical work, co-creation, trash/purge, previews, the dashboard UI, distribution or analytics.
- `reference-script-writing.md` — read when changing `/create/script`, script SSE turns, thinking streams, breakpoints, the clip studio, batch generation or script extract.
