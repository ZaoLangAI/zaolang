# ZaoLang + OpenCut: LLM Implementation Specification

> Purpose: compact source-grounded handoff for implementing OpenCut editing inside ZaoLang.  
> Audience: coding LLMs and engineers.  
> Scope: desktop Web only; no iOS/mobile; no direct social-platform publishing.  
> Audit date: 2026-08-14. Proposed types/APIs below do **not** exist unless marked `EXISTING`.

## 0. Source baseline

| Repo | Local root | Commit | Status |
|---|---|---|---|
| ZaoLang | `sources/zaolang` | `49e323371451ba0a1e73c0aeda441e7a0a5a3f6c` | Product host; proprietary internal |
| OpenCut classic | `sources/opencut-classic` | `cf5e79e919144200294fb9fed22a222592a0aeea` | Editor source; archived; MIT |
| OpenCut rewrite | `sources/opencut-rewrite` | `400f097becba5db0fbc305d5a65348cb81c20356` | Future reference only; MIT |

Local source links in this document are relative to `analysis/`. The audit found 532 ZaoLang, 711 classic, and 80 rewrite Python/TS/TSX/Rust files. Dependencies/builds were not installed or executed; all implementation claims are static-source claims.

## 1. Required outcome

Add a short-drama post-generation editing workflow to ZaoLang:

```text
GenerationJob or Asset
  -> Series / DramaEpisode
  -> EpisodeCut
  -> immutable CutRevision
  -> manual commands or AI EditPlan
  -> DeliveryVariant[]
  -> browser EditorExport[]
  -> Asset
  -> Draft / WorkVersion / PublicationIntent
```

Capabilities:

- Timeline editing: insert, move, trim, split, delete, captions, volume, speed, canvas/brand overlay.
- Manual and AI editing use the same validated command protocol.
- One content cut produces multiple platform/aspect/language/caption/brand variants.
- Browser encodes variants sequentially, uploads to S3/MinIO, then ZaoLang registers `Asset`.
- Internal ZaoLang agents and external LLMs use the same application services.
- External LLM access is Remote MCP over `/mcp` with project authorization.

## 2. Hard decisions and invariants

These are implementation constraints, not suggestions.

1. **Architecture:** ZaoLang product domain + an OpenCut classic adapter. Do not embed the whole OpenCut application.
2. **Source of truth:** PostgreSQL = business state; S3/MinIO = media; OPFS/IndexedDB = disposable cache only.
3. **Public boundary:** never expose OpenCut `TProject`, `TimelineElement`, or Command classes in REST/MCP.
4. **Time:** all edit API times are integer `MediaTime` ticks; `120000 ticks/second`; no float seconds.
5. **Revision:** `CutRevision` is immutable. Mutation creates a new revision using `expected_revision_id` CAS.
6. **Concurrency:** one active write lease per `EpisodeCut`; lease expires after 5 minutes without heartbeat.
7. **AI:** AI creates an inspectable `EditPlan`; domain validation and user confirmation are mandatory.
8. **MCP:** MCP/agents call application services only. They cannot write DB directly, control React, or publish.
9. **Lineage:** internal cut/revision branches do not create remix `LineageEdge` rows.
10. **Publication:** a publication binds an explicit successful export asset; it does not guess the current primary asset.
11. **Export:** MVP exports sequentially in an active Chrome/Edge page; no parallel encoding or headless promise.
12. **Rewrite:** OpenCut rewrite is not an MVP dependency.

## 3. Existing ZaoLang integration points

### 3.1 Product stack

- Frontend: Next.js `16.2.12`, React `19.2.8`, TypeScript `5.9.3`, next-intl. Evidence: [`front/package.json`](../sources/zaolang/front/package.json).
- Backend: FastAPI, SQLAlchemy/Alembic, Python `>=3.12`. Evidence: [`back/pyproject.toml`](../sources/zaolang/back/pyproject.toml).
- Runtime: PostgreSQL, Redis/Celery, S3/MinIO. Evidence: [`README.md`](../sources/zaolang/README.md).
- Generated OpenAPI client types: [`front/src/lib/api/schema.d.ts`](../sources/zaolang/front/src/lib/api/schema.d.ts).

### 3.2 Current short-video flow (`EXISTING`)

```text
front/.../create/short/page.tsx
  -> ShortformStudio
  -> POST /v1/generation-jobs/quote
  -> POST /v1/generation-jobs
  -> jobs._enqueue
  -> Celery dispatch_generation/run_video_generation
  -> run_generation_pipeline -> WorkflowRunner
  -> GenerationJob.output_asset_id + JobEvent SSE
```

Evidence:

- Page: [`create/short/page.tsx`](../sources/zaolang/front/src/app/%5Blocale%5D/%28site%29/create/short/page.tsx).
- UI: [`shortform-studio.tsx`](../sources/zaolang/front/src/components/shortform/shortform-studio.tsx), `ShortformStudio`.
- API: [`api/v1/jobs.py`](../sources/zaolang/back/app/api/v1/jobs.py), `create_job`, `_enqueue`.
- Worker: [`workers/tasks.py`](../sources/zaolang/back/app/workers/tasks.py), `dispatch_generation`, `run_video_generation`.
- Pipeline: [`workers/pipeline.py`](../sources/zaolang/back/app/workers/pipeline.py), `run_generation_pipeline`.

Insert the editor domain **after** `GenerationJob.output_asset_id/Asset` and **before** Draft/Work publication.

### 3.3 Existing series model must be reused

ZaoLang already has:

- `Series(id="ser_", owner_user_id, title, description, shortform_profile_key, character_ids_json)` in [`models/characters.py`](../sources/zaolang/back/app/models/characters.py), `Series`.
- `Work.series_id` and `Work.episode_number` in [`models/works.py`](../sources/zaolang/back/app/models/works.py), `Work`.
- Series CRUD and service-level episode conflict checking in [`domain/characters/service.py`](../sources/zaolang/back/app/domain/characters/service.py), `assign_episode`.

Decision:

- Public product term may be `DramaSeries`.
- Database aggregate MUST extend existing `Series`; do not create a second independent series table.
- Add `DramaEpisode` for production-time episodes. Published `Work` remains the public projection.

### 3.4 Existing publication and lineage invariants

Relevant models in [`models/works.py`](../sources/zaolang/back/app/models/works.py):

- `Draft`: source work version, license snapshot, output asset, latest job.
- `WorkVersion`: immutable published snapshot, `primary_output_asset_id`.
- `LicenseSnapshot`: frozen license terms.
- `LineageEdge`: exactly one parent relation for a published remix version.
- `PublicationIntent`: currently points to `work_id`; download uses the work version primary output.

Publishing logic: [`domain/publishing/service.py`](../sources/zaolang/back/app/domain/publishing/service.py). Shortform publication: [`domain/shortform/service.py`](../sources/zaolang/back/app/domain/shortform/service.py), `create_publication_intent`.

Required changes:

- `Draft`: add nullable `source_cut_revision_id`, `delivery_variant_id`.
- `WorkVersion`: add nullable `editor_export_id`; keep `primary_output_asset_id` for compatibility.
- `PublicationIntent`: add nullable `delivery_variant_id`, `editor_export_id`.
- Binding service MUST verify export success, asset ownership, license, moderation, variant spec, and user confirmation.
- Only an actual remix of another published `WorkVersion` creates `LineageEdge`.

### 3.5 Existing asset contract

Models: [`models/media.py`](../sources/zaolang/back/app/models/media.py), `Asset`, `UploadSession`, `AssetConsent`, `ContentFingerprint`, `ProvenanceManifest`.

Flow:

```text
POST /v1/uploads/presign -> browser PUT -> POST /v1/uploads/complete -> Asset
```

Implementation: [`domain/media/service.py`](../sources/zaolang/back/app/domain/media/service.py). Current MIME and purpose policies: [`storage/s3.py`](../sources/zaolang/back/app/storage/s3.py).

Required additions:

- Purposes: `editor_source`, `editor_export`, optionally `caption`, `font`.
- Bind export upload session to `(user_id, export_id, MIME, max_size, object_key, checksum)`.
- `complete` MUST perform object HEAD/probe/checksum before registering `Asset`.
- Revision documents store `asset_id`, never object keys or persistent signed URLs.

### 3.6 Existing auth, API and events to reuse

- API client refresh/idempotency: [`front/src/lib/api/client.ts`](../sources/zaolang/front/src/lib/api/client.ts).
- Upload client: [`front/src/lib/upload.ts`](../sources/zaolang/front/src/lib/upload.ts).
- SSE resume with `Last-Event-ID`: [`front/src/lib/use-job-stream.ts`](../sources/zaolang/front/src/lib/use-job-stream.ts).
- Gapless event sequence and conditional state updates: [`domain/jobs/state_machine.py`](../sources/zaolang/back/app/domain/jobs/state_machine.py), `append_event`, `events_since`, `transition`.
- Credits reserve/capture/release: [`domain/credits/service.py`](../sources/zaolang/back/app/domain/credits/service.py).

Editor export/AI operations SHOULD reuse these patterns, not necessarily reuse `GenerationJob` rows.

### 3.7 Existing agent extension points

- `AgentProfile`, `AgentSkill`: [`models/agent_skills.py`](../sources/zaolang/back/app/models/agent_skills.py).
- `AgentRun`: [`models/generation.py`](../sources/zaolang/back/app/models/generation.py).
- Role registry: [`domain/agent_skills/presets.py`](../sources/zaolang/back/app/domain/agent_skills/presets.py), `ROLE_PRESETS`.
- Prompt slots: [`agents/slots.py`](../sources/zaolang/back/app/agents/slots.py), `PROMPT_SLOTS`.
- Agent execution: [`agents/base.py`](../sources/zaolang/back/app/agents/base.py), `run_agent`.
- Read-only/advisory tool whitelist: [`agents/tools.py`](../sources/zaolang/back/app/agents/tools.py), `TOOL_REGISTRY`.

Add a dedicated `editor_planner`; do not reuse the generic generation planner.

## 4. OpenCut source facts

### 4.1 Classic is the editor source

Stack: Next `16.1.3`, React 19, TypeScript `5.8.3`, Bun `1.2.18`, MediaBunny `1.29.1`, `opencut-wasm 0.2.10`, Zustand 5. Evidence: [`apps/web/package.json`](../sources/opencut-classic/apps/web/package.json).

Editor chain:

```text
EditorProvider
  -> EditorCore singleton
  -> Timeline/Media/Scenes managers
  -> CommandManager.execute(Command)
  -> project/timeline state
  -> RendererManager
  -> CanvasRenderer + WasmCompositor
  -> SceneExporter
  -> MediaBunny Output(BufferTarget)
```

Evidence:

- [`components/providers/editor-provider.tsx`](../sources/opencut-classic/apps/web/src/components/providers/editor-provider.tsx), `EditorProvider`.
- [`core/index.ts`](../sources/opencut-classic/apps/web/src/core/index.ts), `EditorCore`.
- [`core/managers/commands.ts`](../sources/opencut-classic/apps/web/src/core/managers/commands.ts), `CommandManager`.
- [`core/managers/renderer-manager.ts`](../sources/opencut-classic/apps/web/src/core/managers/renderer-manager.ts), `RendererManager`.
- [`services/renderer/scene-exporter.ts`](../sources/opencut-classic/apps/web/src/services/renderer/scene-exporter.ts), `SceneExporter`.

### 4.2 Reusable classic capabilities

| Capability | Source |
|---|---|
| Project/scenes | [`project/types.ts`](../sources/opencut-classic/apps/web/src/project/types.ts), `TProject` |
| Tracks/elements | [`timeline/types.ts`](../sources/opencut-classic/apps/web/src/timeline/types.ts), `TScene`, `SceneTracks`, `TimelineElement` |
| Move/trim/split/delete/effects/masks commands | [`commands`](../sources/opencut-classic/apps/web/src/commands) |
| Timeline placement/snapping/zoom | [`timeline`](../sources/opencut-classic/apps/web/src/timeline) |
| SRT/ASS captions | [`subtitles`](../sources/opencut-classic/apps/web/src/subtitles) |
| Volume/audio | [`core/managers/audio-manager.ts`](../sources/opencut-classic/apps/web/src/core/managers/audio-manager.ts) |
| Speed/retime | [`retime`](../sources/opencut-classic/apps/web/src/retime) |
| IndexedDB/OPFS/migrations | [`services/storage`](../sources/opencut-classic/apps/web/src/services/storage) |
| Canvas/WASM render | [`services/renderer`](../sources/opencut-classic/apps/web/src/services/renderer) |
| Exact media time | [`media_time.rs`](../sources/opencut-classic/rust/crates/time/src/media_time.rs), `MediaTime`, `TICKS_PER_SECOND=120000` |
| GPU/compositor/effects/masks | [`rust/crates`](../sources/opencut-classic/rust/crates) |

### 4.3 Critical classic gaps

1. `EditorCore` is a singleton. Refactor to a per-editor disposable instance.
2. `ProjectManager` and save lifecycle assume browser local storage. Replace persistence with ZaoLang revision service; retain OPFS/IndexedDB as cache.
3. OpenCut commands are executable classes, not wire-safe JSON DTOs. Add a strict `CommandCodec`.
4. [`commands/batch-command.ts`](../sources/opencut-classic/apps/web/src/commands/batch-command.ts) runs commands sequentially and does not roll back a partial failure.
5. [`scene-exporter.ts`](../sources/opencut-classic/apps/web/src/services/renderer/scene-exporter.ts) uses `BufferTarget` and returns the entire output `ArrayBuffer`; long exports can exhaust memory.
6. Transition UI says `Transitions view coming soon...`; video transitions are not an implemented capability. Evidence: [`assets/index.tsx`](../sources/opencut-classic/apps/web/src/components/editor/panels/assets/index.tsx).
7. Classic is archived/unmaintained. Evidence: [`README.md`](../sources/opencut-classic/README.md).
8. Mobile/iPad are explicitly unsupported. Evidence: [`mobile-gate.tsx`](../sources/opencut-classic/apps/web/src/components/editor/mobile-gate.tsx).

### 4.4 Rewrite is not usable yet

- Web editor says `Coming soon.`: [`apps/web/src/routes/editor.tsx`](../sources/opencut-rewrite/apps/web/src/routes/editor.tsx).
- Cargo workspace comments out `crates/*`: [`Cargo.toml`](../sources/opencut-rewrite/Cargo.toml).
- README lists Editor API, Rust core, plugins and MCP as goals: [`README.md`](../sources/opencut-rewrite/README.md).
- No usable editor core/public API/MCP implementation was found in the fixed tree.

Preserve adapter ports so a later rewrite core can replace classic without changing ZaoLang APIs.

## 5. Target module layout

Suggested placement; adapt names to ZaoLang conventions during implementation.

```text
back/app/
  models/editor.py
  domain/editor/
    service.py              # ownership, revisions, plans, variants
    state_machine.py        # EditPlan/EditorExport conditional transitions
    command_validation.py
    leases.py
    exports.py
  api/v1/editor.py
  api/schemas/editor.py
  mcp/
    server.py
    auth.py
    resources.py
    prompts.py
    tools.py
  workers/media_analysis.py

front/src/features/editor/
  api/
  engine/
    ports.ts
    command-codec.ts
    transactional-batch.ts
    classic/
  session/
  timeline/
  preview/
  export-runner/

third_party/opencut-classic/   # production fork/provenance; not the audit source tree
```

Stable ports:

```ts
interface EditorEngine {
  load(document: EditorDocumentEnvelope, assets: ResolvedAsset[]): Promise<void>;
  apply(batch: EditCommandBatch): Promise<ApplyResult>;
  snapshot(): Promise<EditorDocumentEnvelope>;
  renderPreview(time: MediaTime): Promise<void>;
  dispose(): Promise<void>;
}

interface RendererBackend {
  preflight(spec: VariantSpec): Promise<CapabilityReport>;
  export(spec: VariantSpec, signal: AbortSignal): AsyncIterable<ExportProgress>;
}

interface CommandCodec {
  validate(input: unknown): EditCommandBatch;
  toClassic(batch: EditCommandBatch, context: MappingContext): ClassicCommand[];
}
```

## 6. Domain model

Hierarchy:

```text
Series (public alias DramaSeries)
  -> DramaEpisode
  -> EpisodeCut
  -> CutRevision
  -> DeliveryVariant
  -> EditorExport
```

### 6.1 Tables

| Table | Required fields | Constraints |
|---|---|---|
| existing `series` | add `kind`, `default_locale`, `brand_pack_asset_id?`, `status` | index `(owner_user_id,kind)`; archive after use |
| `drama_episodes` | `id dep_`, `series_id`, `episode_number`, `title`, `synopsis?`, `script_json`, `status`, `canonical_work_id?` | unique `(series_id,episode_number)`; series RESTRICT |
| `episode_cuts` | `id cut_`, `episode_id`, `kind`, `name`, `status`, `head_revision_id?`, `base_cut_id?` | unique `(episode_id,kind,name)`; archive, do not hard-delete used cuts |
| `cut_revisions` | `id crv_`, `cut_id`, `revision_no`, `parent_revision_id?`, `engine`, `engine_schema_version`, `document_json`, `asset_bindings_json`, `duration_ticks`, `content_hash`, `command_summary_json`, creator fields | unique `(cut_id,revision_no)` and `(cut_id,content_hash)`; immutable; parent RESTRICT |
| `edit_plans` | `id epl_`, `cut_id`, `base_revision_id`, `status`, `schema_version`, `commands_json`, `diff_json`, `validation_json`, `agent_run_id?`, model/prompt/token/latency fields, `applied_revision_id?`, `expires_at` | a plan applies once; base revision must still match |
| `delivery_variants` | `id dvr_`, `cut_revision_id`, `profile_key`, aspect/size/fps/format, caption language/mode, `brand_pack_id?`, `spec_json`, `spec_hash`, `status` | unique `(cut_revision_id,spec_hash)`; spec immutable |
| `editor_exports` | `id exp_`, `variant_id`, `status`, `operation_key`, `attempt`, lease/runner fields, progress, `output_asset_id?`, checksum/size, failure, timestamps, cancel request | unique `(variant_id,operation_key)`; terminal state cannot reopen |
| `media_analyses` | `id man_`, `asset_id`, analyzer/version/status, transcript/shots/focus/audio JSON, `duration_ticks`, result hash/failure | unique `(asset_id,analyzer,analyzer_version)` |
| `editor_leases` | `id els_`, `cut_id`, `user_id`, `browser_instance_id`, `token_hash`, `base_revision_id`, `last_sequence`, expiry/revocation | one unexpired/unrevoked write lease per cut |
| `editor_command_events` | lease/sequence/batch, expected/result revision, commands/status/error | unique `(lease_id,sequence)` and `batch_id` |

### 6.2 Semantics

- `EpisodeCut.kind`: `full | condensed | trailer | highlight | custom`.
- `DeliveryVariant` is platform delivery metadata, not a new content edit.
- Engine JSON is private and versioned. Public APIs return a normalized timeline summary.
- `content_hash` is computed from canonical normalized document + asset bindings.
- Use DB `BIGINT` for ticks. Validate JavaScript safe integer range at REST/MCP boundaries.
- Revision creation and `episode_cuts.head_revision_id` update occur in one transaction with CAS.

### 6.3 State machines

```text
EpisodeCut: draft -> editing -> ready -> archived
EditPlan: generating -> validated -> applied
                    \-> rejected | expired | failed
DeliveryVariant: draft -> ready -> exporting -> succeeded
                                \-> failed | cancelled
EditorExport: queued -> claimed -> encoding -> uploading -> verifying -> succeeded
                   \-> cancel_requested -> cancelled
                   \-> failed
```

Implement transitions using conditional `UPDATE ... WHERE status IN (...)`, matching ZaoLang job transitions. Late heartbeat/callback MUST NOT reopen a terminal row.

## 7. Edit command contract

MVP command types:

```text
insert_clip
delete_elements
move_elements
trim_element
split_element
set_clip_volume
set_clip_speed
insert_caption
update_caption
set_canvas
set_brand_overlay
```

Rules:

- Strict JSON Schema 2020-12; root object; `additionalProperties:false`.
- No generic `update_property(path,value)`.
- Every referenced asset/track/element must exist and belong to the project.
- Every time is integer ticks and must be within media bounds.
- Default limits: 100 commands/batch, 5000 elements/document, 5 MB document; make configurable.
- Manual UI and AI/MCP MUST produce this same contract.
- Native OpenCut commands are created only inside `CommandCodec.toClassic`.

Example:

```json
{
  "schema_version": 1,
  "batch_id": "01J...",
  "expected_revision_id": "crv_007",
  "commands": [
    {"type":"split_element","element_id":"el_9","at_ticks":1440000},
    {"type":"set_clip_volume","element_id":"el_10","volume_millipercent":85000}
  ]
}
```

### 7.1 Transactional application

Classic `BatchCommand` is not transactional. Adapter algorithm:

```text
validate schema
-> authorize every asset/resource
-> validate base revision and lease
-> clone editor state or create reversible snapshot
-> map all commands
-> execute sequentially
-> if any fails: undo executed prefix in reverse or discard clone
-> validate resulting document
-> canonicalize + hash
-> persist one immutable CutRevision + CAS head
```

No failed batch may alter the visible/persisted head.

## 8. REST API proposal

All endpoints below are `PROPOSED`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/drama-series` | create extended existing Series |
| `GET /v1/drama-series[/{id}]` | list/read series aggregate |
| `POST /v1/drama-series/{id}/episodes` | create production episode |
| `POST /v1/drama-episodes/{id}/cuts` | create cut from asset or generation job |
| `GET /v1/episode-cuts/{id}` | cut/head/lease summary |
| `POST /v1/episode-cuts/{id}/leases` | acquire single writer |
| `POST /v1/episode-cuts/{id}/leases/{lease}/heartbeat` | renew lease |
| `DELETE /v1/episode-cuts/{id}/leases/{lease}` | release lease |
| `POST /v1/episode-cuts/{id}/revisions` | apply command batch and create revision |
| `POST /v1/episode-cuts/{id}/edit-plans` | start AI plan operation |
| `POST /v1/edit-plans/{id}/apply` | validate/apply selected commands |
| `POST /v1/edit-plans/{id}/reject` | reject plan |
| `POST /v1/cut-revisions/{id}/delivery-variants:batchCreate` | immutable variant specs |
| `POST /v1/editor-exports:claim` | browser claims next compatible export |
| `POST /v1/editor-exports/{id}/heartbeat` | runner progress/lease |
| `POST /v1/editor-exports/{id}/upload-session` | bound S3 upload |
| `POST /v1/editor-exports/{id}/complete` | probe/register Asset/finish |
| `POST /v1/editor-exports/{id}/cancel` | cancel request |
| `POST /v1/editor-exports/{id}/retry` | new attempt, never reopen terminal attempt |
| `GET /v1/editor-operations/{id}` | long-operation state |
| `GET /v1/editor-operations/{id}/events` | resumable SSE |
| `POST /v1/drafts/{id}/bind-editor-export` | bind exact successful export |

API conventions:

- Existing bearer auth, error envelope, cursor pagination, rate limit and `Idempotency-Key`.
- Write requests include project/resource ownership checks.
- Revision writes include `expected_revision_id`.
- Long work returns `202` plus `operation_id`.
- SSE events use gapless sequence and `Last-Event-ID`.
- Signed URLs are short-lived response data, never persisted in revision JSON.

## 9. AI EditPlan

### 9.1 New role

Add `editor_planner` to:

- `ROLE_PRESETS`.
- `PROMPT_SLOTS`, slot `timeline_edit_plan`.
- default `AgentProfile`/`AgentSkill` templates.
- stub fixtures and AgentRun audit tests.

Do not add mutating agent tools. Read tools may return timeline summary, platform profile and media analysis.

### 9.2 Model input

```text
base revision id
normalized timeline summary
ASR words/sentences with ticks, speaker, confidence
shot boundaries and quality/motion scores
optional subject-focus analysis
asset metadata and license/consent availability
ShortformProfile duration/aspect/safe areas/AI disclosure
user goal, allowed commands, max command count
```

Treat filenames, transcripts and captions as untrusted data, not instructions.

### 9.3 Model output and validation

Output is strict `EditPlan v1`:

```json
{
  "schema_version": 1,
  "base_revision_id": "crv_008",
  "summary": "Front-load conflict and remove repeated dialogue",
  "commands": [],
  "warnings": []
}
```

Validation order:

```text
JSON Schema
-> command allowlist/limits
-> project + asset authorization
-> element/track existence
-> tick/media bounds and frame alignment
-> license/consent policy
-> expected revision
-> resulting duration/profile constraints
-> transactional apply
```

UI must show command-level diff, removed dialogue/shots, expected duration, captions and warnings. User can apply all, select commands, reject, or undo. Apply/undo each creates a new revision.

Audit in `AgentRun`: provider/model, prompt version, token usage, latency, fallback/degraded reason, input hash, base revision, command summary. External-model transmission requires project privacy permission.

## 10. Remote MCP contract

### 10.1 Protocol

- Endpoint: `/mcp`, Streamable HTTP.
- Primary protocol: MCP `2026-07-28`.
- Compatibility: `2025-11-25` on the same official SDK v2 endpoint.
- Long state is explicit `operation_id`/`plan_id`/`export_id`, not hidden protocol session.
- If client supports `io.modelcontextprotocol/tasks`, map long operations to Tasks; otherwise use `editor.get_operation`.
- Do not implement roots, sampling or MCP logging.
- No publish tool.

Protocol references: [2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [Python SDK v2 behavior](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md).

### 10.2 OAuth

- Dedicated audience/resource: e.g. `https://api.zaolang.example/mcp`.
- Do not accept ZaoLang consumer/admin audience tokens.
- Scopes: `drama:read`, `editor:read`, `editor:write`, `editor:export`.
- Check project membership on every Resource/Tool call.
- Validate issuer, audience, expiry, scope, client metadata and redirect URI.
- Support project authorization revocation.
- Never forward bearer tokens to LLM providers or S3.
- Rate-limit by `(client_id, subject, project_id, tool)`.
- Audit client, subject, project, tool, input hash, trace ID and result handle.

### 10.3 Resources

```text
zaolang://projects/{project}/dramas/{series}
zaolang://projects/{project}/episodes/{episode}
zaolang://projects/{project}/cuts/{cut}
zaolang://projects/{project}/revisions/{revision}/summary
zaolang://projects/{project}/variants/{variant}
zaolang://projects/{project}/exports/{export}
zaolang://projects/{project}/media/{asset}/analysis
```

Resources return metadata/summaries, not persistent media URLs or raw private video.

### 10.4 Prompts

| Prompt | Input | Function |
|---|---|---|
| `short_drama_edit_plan` | cut, goal, profile, max commands | structured EditPlan context |
| `short_drama_trailer_plan` | cut, target ticks, spoiler policy | trailer plan only |
| `delivery_variant_review` | variant, locale | spec/safe-area/caption review |

### 10.5 Tools

| Tool | Scope | Result |
|---|---|---|
| `drama.list_series` | `drama:read` | page of series |
| `drama.get_episode` | `drama:read` | episode/cut summaries |
| `editor.create_cut` | `editor:write` | cut + initial revision IDs |
| `editor.get_timeline_summary` | `editor:read` | normalized summary |
| `editor.generate_edit_plan` | `editor:write` | operation/task + plan ID |
| `editor.apply_edit_plan` | `editor:write` | new revision + diff summary |
| `editor.reject_edit_plan` | `editor:write` | terminal plan status |
| `editor.create_variants` | `editor:write` | immutable variants |
| `editor.queue_exports` | `editor:export` | operation/task + export IDs |
| `editor.get_operation` | `editor:read` | state/progress/result/error |
| `editor.cancel_operation` | `editor:export` | `cancel_requested` |

Every tool input:

- JSON Schema 2020-12, object root, `additionalProperties:false`.
- Requires `project_id`.
- Write tools require `idempotency_key`; revision mutation requires `expected_revision_id`.
- Array/string/integer maximums are explicit.

Stable business error codes:

```text
UNAUTHENTICATED
SCOPE_REQUIRED
PROJECT_FORBIDDEN
NOT_FOUND
VALIDATION_FAILED
REVISION_CONFLICT
LEASE_HELD
BATCH_ROLLED_BACK
OPERATION_TERMINAL
RATE_LIMITED
MODEL_UNAVAILABLE
BROWSER_REQUIRED
```

Never expose SQL, stack traces, local paths, secrets or signed URLs in errors.

Forbidden tools: direct publish, delete asset, arbitrary file/SQL access, raw React/editor control.

## 11. Browser session and export protocol

### 11.1 Write session

```text
open editor
-> acquire EditorLease
-> load head revision and resolve assets
-> heartbeat every 30s
-> receive command batches over resumable SSE
-> transactional apply
-> save immutable revision with CAS
-> release lease or expire after 5min
```

On lease loss: stop writes, switch to read-only, keep an optional local recovery bundle, never overwrite the new head.

### 11.2 Sequential export

```text
queued
-> browser claim + capability report
-> preflight storage/codec/memory
-> encoding
-> S3 upload
-> server HEAD/checksum/ffprobe verification
-> Asset registration
-> EditorExport succeeded
```

Rules:

- Queue may contain 6–20 variants; one browser encodes one at a time.
- Variant spec is immutable at queue time.
- Heartbeat every 15s or 2% progress.
- Check cancellation during frame loop, audio processing and upload parts.
- Use export-bound upload purpose and short-lived URLs.
- Successful upload without `complete` is reconciled by checksum/object key.
- Same operation key cannot register two successful assets.
- MVP must cap duration/resolution/output estimate because classic uses `BufferTarget` and full `AudioBuffer`.
- Production should replace `BufferTarget` with streaming/file-backed output or retain a documented hard product cap.

Recovery codes:

| Failure | Required action |
|---|---|
| page/browser lost | lease expires; mark `RUNNER_LOST`; requeue or retry attempt |
| codec unsupported | fail with capabilities; never silently change variant |
| upload interrupted | resume multipart/OPFS temp when possible |
| URL expired | issue a new URL for same bound upload |
| storage insufficient | reject at preflight; do not delete server assets |
| GPU/context lost | rebuild renderer or fail/retry; record fallback |
| revision conflict | return current head + diff handle; do not auto-merge |

## 12. OpenCut port matrix

| Classic module | Disposition | Required adaptation | Risk |
|---|---|---|---|
| `EditorCore` | refactor | instance factory, disposal, injected ports | high |
| `CommandManager` | reuse via adapter | wire codec, revision/hash hooks | high |
| `BatchCommand` | replace/wrap | atomic rollback semantics | critical |
| timeline types/controllers | reuse internally | stable IDs, ticks, ZaoLang UI/theme | medium |
| `TProject` | private engine payload | envelope/schema version; never public | high |
| `ProjectManager`/SaveManager | refactor | server revisions; OPFS cache only | critical |
| IndexedDB/OPFS migrations | partial reuse | cache namespace/eviction/user isolation | high |
| RendererManager/CanvasRenderer | adapt | variant spec, capability/context recovery | high |
| SceneExporter/MediaBunny | MVP adapt, then replace buffer target | sequential queue, limits, upload | critical |
| subtitles | reuse/adapt | server caption truth, fonts, safe area | medium |
| audio/retime | reuse/adapt | sample/channel policy, A/V sync | high |
| effects/masks | phase 2 | allowlist and GPU tests | high |
| transitions | do not claim/reuse | new implementation later | high |
| Rust `time` | adopt | shared ticks contract | low |
| Rust GPU/compositor/WASM | fork/reuse | pinned toolchain, SBOM, browser tests | high |

## 13. Delivery plan

### Phase 0: prove the technical path

1. Create production OpenCut classic fork with MIT NOTICE/provenance.
2. Pin Rust/Bun/Node/WASM toolchain and build classic.
3. Export a 10-second MP4/WebM golden sample in target Chrome/Edge.
4. Prove multiple `EditorCore` instances or finish instance refactor.
5. Prove `CommandCodec` + atomic failure rollback.
6. Prove S3 CORS, bound upload and server ffprobe.

Stop/re-scope if the fixed classic tree cannot produce stable target-browser output.

### Phase 1: domain and basic editor

1. Shared MediaTime/FrameRate/EditCommand/Variant schemas.
2. Series extension + DramaEpisode/EpisodeCut/CutRevision migrations/services/APIs.
3. Revision CAS, lease/heartbeat/expiry, command SSE.
4. Asset resolver and editor upload purposes.
5. ZaoLang editor shell using its design system/next-intl/a11y.
6. Insert/move/trim/split/delete/caption/volume/speed/canvas.

### Phase 2: variants and export

1. MediaAnalysis: ffprobe, ASR, shot detection; subject focus optional.
2. DeliveryVariant/spec hash/platform safe areas/brand/caption language.
3. EditorExport state machine and browser runner.
4. S3 upload/complete/reconciliation.
5. Explicit Draft/WorkVersion/PublicationIntent binding.
6. Six-or-more sequential variant E2E.

### Phase 3: AI and MCP

1. `editor_planner`, strict EditPlan, diff/apply/reject/undo, AgentRun audit.
2. `/mcp` read Resources/Prompts/Tools first.
3. Dedicated OAuth audience/scopes/revocation/audit.
4. Enable write/export tools after authorization and idempotency tests.
5. Test MCP 2026-07-28 and 2025-11-25; Tasks and operation fallback.

### Phase 4: production hardening

1. Long media/memory/GPU/browser matrix.
2. Streaming/file-backed export or enforce product caps.
3. Security/IDOR/prompt injection/privacy/license tests.
4. Observability, orphan cleanup, runbooks, flags and staged rollout.
5. Re-evaluate rewrite every 6–8 weeks through adapter ports only.

## 14. Effort estimate

Person-weeks, based on source coupling rather than LOC:

| Workstream | Optimistic | Expected | Conservative |
|---|---:|---:|---:|
| Domain models/APIs | 4 | 6 | 8 |
| Classic extraction/adapter/commands | 8 | 12 | 17 |
| ZaoLang UI/i18n/a11y | 4 | 6 | 9 |
| Media analysis | 3 | 5 | 8 |
| Variants/browser export | 5 | 8 | 12 |
| AI EditPlan | 4 | 6 | 9 |
| MCP/OAuth | 5 | 8 | 12 |
| Tests/security/production hardening | 6 | 10 | 14 |
| Mechanical total | 39 | 61 | 89 |

Practical ranges after parallel work:

- Constrained MVP: 38–52 person-weeks; 4–5 engineers; 12–16 calendar weeks.
- Production: 58–85 person-weeks; 5–7 engineers; 18–26 calendar weeks.

Recommended roles: tech lead, two frontend/media engineers, two backend/domain/MCP engineers, AI/media-analysis engineer, QA/SDET; part-time security/legal/design.

## 15. Acceptance gates

### Correctness

- Manual and AI actions use identical `EditCommand` semantics.
- Failed batch leaves head/document unchanged.
- Conflicting revision returns 409 and never overwrites.
- Undo/restoration creates an auditable new revision.
- Internal revisions never create remix lineage.
- Publication download checksum equals the selected `EditorExport.output_asset_id`.

### Media

- At least six variants run sequentially; one failure does not corrupt others.
- A/V sync and caption timing error <= 1 frame on golden samples.
- Output size/aspect/fps/safe area match immutable variant spec.
- Test H.264/AAC, VP9/Opus, VFR, no-audio, multichannel, CJK/English, corrupt input.

### Concurrency/recovery

- Two tabs cannot both hold write lease.
- Lease loss changes editor to read-only.
- Last-Event-ID resumes command/export events without gaps.
- Duplicate idempotency/complete calls do not duplicate revisions/assets.
- Test page close, URL expiry, upload interruption, low storage, context loss.

### AI/MCP/security

- Invalid JSON, hallucinated assets/elements, out-of-range ticks and oversized plans are rejected.
- Wrong audience/scope/project/token revocation is rejected across Tool/Resource/SSE/signed URL paths.
- MCP 2026 and 2025 contract tests pass.
- Private media is not sent to external models without project authorization.
- No MCP direct-publish path exists.

## 16. Feature flags

Add to existing [`FeatureFlags`](../sources/zaolang/back/app/platform_config/schemas.py):

```text
drama_studio_enabled
web_editor_enabled
variant_export_enabled
editor_ai_enabled
editor_mcp_enabled
```

Dependencies:

```text
variant_export -> web_editor
editor_ai -> web_editor
editor_mcp write/export -> web_editor
```

Rollout: internal -> selected projects -> 5% -> 20% -> 50% -> 100%. Monitor export failure/OOM, revision conflict, orphan upload, invalid AI plan, MCP forbidden/rate-limit events.

## 17. External requirements and major risks

| Requirement/risk | Required response |
|---|---|
| Desktop Chrome/Edge only | capability probe; support last two stable versions |
| WebGPU/WebCodecs variability | tested fallback/read-only behavior; GPU/OS matrix |
| OPFS quota/eviction | cache only; storage estimate and recovery |
| Rust/WASM supply chain | pin locks/toolchain; self-build; SBOM/SCA |
| ffprobe | fixed worker version for output verification |
| ASR/shot provider | version results; privacy/cost policy; fallback |
| S3 large uploads | strict CORS, multipart resume, short URL TTL, orphan sweeper |
| Classic archived | owned fork and security/browser maintenance |
| In-memory export | MVP caps; production streaming/file target |
| Proprietary + MIT | retain OpenCut MIT notice; ZaoLang itself is proprietary internal software; legal review |
| MCP prompt injection/IDOR | structured inputs, per-call ACL, independent OAuth audience, red-team tests |
| External model privacy | project opt-in, minimum context, retention/DPA/region controls |

## 18. Implementation task DAG

Use these IDs in follow-up LLM tasks.

```text
T01 classic fork/provenance/toolchain
T02 golden export/browser capability spike          <- T01
T03 shared time/command/variant schemas
T04 EditorEngine + CommandCodec ports              <- T01,T03
T05 atomic command adapter                         <- T04
T06 Series extension + episode/cut/revision DB/API <- T03
T07 revision CAS + lease + command SSE             <- T06
T08 editor upload purposes + Asset resolver        <- T06
T09 ZaoLang editor shell/i18n/a11y                 <- T04,T06,T08
T10 MVP timeline features                          <- T05,T09
T11 MediaAnalysis workers                          <- T08
T12 DeliveryVariant domain                         <- T06,T11
T13 EditorExport state/browser protocol            <- T02,T07,T12
T14 S3 export upload/verify/recovery                <- T08,T13
T15 Draft/WorkVersion/PublicationIntent binding    <- T14
T16 editor_planner + EditPlan audit                <- T05,T11
T17 EditPlan diff/apply/reject/undo                <- T07,T10,T16
T18 MCP read server/resources/prompts              <- T06,T11
T19 MCP OAuth/scopes/project ACL                    <- T18
T20 MCP write/export tools                         <- T13,T17,T19
T21 media/concurrency/security/MCP E2E              <- T15,T20
T22 flags/metrics/runbooks/rollout                  <- T21
T23 streaming/file-backed export                   <- T13 (production gate or retain caps)
```

## 19. Known unverified items

- ZaoLang pytest/frontend build not run.
- Classic Bun tests/Next build not run.
- Rust tests/wasm-pack build not run.
- Real 10-second export not run.
- Sparse/partial clones omit nonessential static assets and full Git history.
- OpenCut built-in fonts/stickers/model resources need a separate license/runtime audit.
- MCP `2026-07-28` is recent; pin and reconfirm the official SDK/conformance at implementation time.

Do not report any of these as passing until Phase 0 produces evidence.

## 20. One-paragraph implementation directive

Implement short-drama editing as a new ZaoLang domain inserted between generated `Asset` and existing Draft/Work publication. Extend existing `Series`; add production episodes, content cuts, immutable revisions, delivery variants, exports and leases. Fork only the reusable OpenCut classic engine modules behind `EditorEngine`, `CommandCodec` and `RendererBackend`; replace local-first persistence with server revisions while retaining OPFS as cache. Use integer ticks, atomic command batches, single-writer leases, sequential browser export and explicit export-to-publication binding. Add `editor_planner` whose strict EditPlan uses the same commands as manual editing. Expose application services through project-scoped Remote MCP with independent OAuth audience/scopes, explicit operation handles, no direct DB/UI access and no publish tool. Treat OpenCut rewrite as a future adapter replacement, not an implementation dependency.
