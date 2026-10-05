---
name: zaolang-blocking-studio
description: 白膜 3D blockout studio for script episodes — blocking document, sanitizer, blocking_route/derive turns, TS compiler, three.js player, motion-guide reference video. Use when touching /create/script/{id}/blocking, app.domain.blocking, features/blocking or motion_guide routing.
---

# 白膜 Blockout Studio

**Scope**: 3D previs over the same `DramaEpisode` as 文案创作 — sets, mannequins, per-segment shots — edited by chat or drag, rendered per segment as a reference video. Needs `blocking_studio_enabled` **and** `script_studio_enabled` (`service.py:is_enabled`); else `ScriptDetailResponse.blocking` is `null`.
Not here → `zaolang-editor-drama` (scripts, turns), `zaolang-media-assets` (reference upload, CFR conform), `zaolang-generation-jobs` (submit).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/blocking/vocabulary.py` | closed presets (`CameraMove`, sizes, actions…) + limits; source for schemas, sanitizer, prompt |
| `back/app/domain/blocking/segments.py` | `ordered_segments` (port of `orderedBreakpointKeys`), duration estimate, source hashes |
| `back/app/domain/blocking/camera_language.py` | `parse_camera_text` (camera block → size/move), `normalize_token` (Chinese/film shorthand) |
| `back/app/domain/blocking/sanitize.py` | `sanitize_blocking`, `fit_durations`, `_reconcile_with_script`, `stale_segment_keys` |
| `back/app/domain/blocking/service.py` | `stream_blocking_turn` (`PhaseMarker` route → script → blocking; rebuild skips route/script), `prepare_rebuild`, `patch_manual`, `update_settings`, `get_version` |
| `back/app/api/schemas/blocking.py` | `BlockingDocument`/`BlockingState` (+ Literal vocab); `front/src/features/blocking/types.ts` only aliases the generated schema |
| `back/app/models/editor.py:EpisodeBlockingVersion` | history (`version_no`, origin `llm_turn`/`rebuild`/`manual`); head is `DramaEpisode.blocking_json` |
| `back/app/agents/blocking_director.py` | `copy` slots `blocking_route` (JSON) and `blocking_derive` (streamed) |
| `back/app/api/v1/blocking.py` | `/v1/scripts/{id}/blocking/turns`, `blocking:rebuild` (SSE); PATCH blocking/settings; GET versions |
| `back/app/domain/media/reference_roles.py` | motion-guide directive, applied in `back/app/workflows/nodes.py:_plan_enhancements` |
| `front/src/features/blocking/compiler/` | pure `compileBlocking`; `camera.ts`, `obstacles.ts` (A*), `tracks.ts`, `quality.ts` metrics |
| `front/src/features/blocking/engine/` | plain three.js (no r3f): player, mannequin/poses, stage, drag `editor.ts` |
| `front/src/features/blocking/export/render-segment.ts` | segment → clip: WebCodecs+mediabunny, else MediaRecorder |
| `front/src/features/blocking/video-plan.ts` | `planSegmentVideos` (segment duration, linked cast/scene, prompt via `breakpointSegmentPrompt`), `castLegend` (mannequin colour → character); `referenceCamera` sends the opening shot's size/side/height as `reference_shot_size`/`reference_camera_side`/`reference_camera_height` so linked cards lead with the matching angle (AC-3) |
| `front/src/features/blocking/use-blocking-video.ts` | render → upload `generation_reference` → `text_to_video`, `reference_mode: 'input_references'`, `reference_video_role: 'motion_guide'`, with `link_episode_id`/`link_breakpoint_key` |

## Invariants

1. Model writes semantics, never animation: `compileBlocking` is the only motion source; player and exporter both sample it.
2. Every write passes `sanitize_blocking` (`mode="llm"` model, `mode="manual"` browser). `character_ref_id` comes from the script only.
3. Segment `shots[]`: script `camera` blocks are authoritative (`_reconcile_with_script`); staging-only turns reconcile only changed keys (`reconcile_keys`); manual saves never.
4. Compiler repairs staging, never the document: cast ≥ `PERSONAL_SPACE` 0.8m, A* walks on 0.2m `CELL`, cameras track and dodge occlusion. Deterministic.
5. Segment keys = breakpoint keys `{heading}#{ordinal}` (`front/src/features/script/script-breakpoint.ts`); staleness is server side only.
6. A turn edits script only via `copywriter.stream_revise_script`; persists `EpisodeScriptTurn(origin="blocking")` + one `EpisodeBlockingVersion`.
7. `patch_manual`: stale `base_version_no` → 409; saves within 60s (`MANUAL_COALESCE_WINDOW`) coalesce.
8. Durations are whole seconds in [5, 15] (`SEGMENT_MIN_SECONDS`/`SEGMENT_MAX_SECONDS`), fitted by `fit_durations`.
9. Render colours are fixed (`palette.ts`), not theme tokens, so exports match across themes; cast tags are CSS2D, never in frames.
10. WebCodecs needs `window.isSecureContext`; on plain HTTP `render-segment.ts` records via MediaRecorder in real time (MP4 avc1 else WebM), upload mime matches.
11. Motion guides route only to `accepts_video_reference` non-EDIT models (`back/app/agents/router.py`); need `text_to_video` + `input_references` (`back/app/api/schemas/jobs.py`) + exactly one video (`back/app/domain/media/service.py`).
12. three.js (`blocking-viewport.tsx`) and mediabunny load by dynamic `import()`; the page statically imports only the compiler. Destructure straight off `await import('mediabunny')` — `Promise.all` defeats tree-shaking; `front/scripts/bundle-budget.json` gates size.

## Recipes

1. **Add a camera move**: `CameraMove` Literal in `vocabulary.py` → `make openapi` (`types.ts` derives it; TS then fails until handled) → `CAMERA_MOVES` label in `vocabulary.ts` + messages → `compiler/camera.ts` → `normalize_token` aliases → tests.
2. **Add a compiler repair**: implement in `compiler/`, add a `quality.ts` metric, pin in `compile.test.ts`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_blocking_segments.py tests/unit/test_blocking_sanitize.py tests/unit/test_blocking_camera_language.py tests/unit/test_motion_guide_routing.py tests/integration/test_blocking.py
cd front && npx vitest run src/features/blocking && npm run check:messages
make openapi-check
```
