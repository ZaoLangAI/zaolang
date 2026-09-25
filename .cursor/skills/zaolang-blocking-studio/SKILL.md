---
name: zaolang-blocking-studio
description: 白膜 (3D blockout / previs) studio for a script episode — the semantic blocking document and its sanitizer, the blocking_route/blocking_derive agent slots and the three-phase SSE turn that can rewrite the script too, manual saves with version CAS, the deterministic TS compiler, the plain-three.js player/mannequins/drag editor, and rendering a segment to MP4 as a motion-guide reference video (`reference_video_role="motion_guide"`). Use when touching /create/script/{id}/blocking, app.domain.blocking, blocking_director, episode_blocking_versions, DramaEpisode.blocking_json/target_duration_seconds, front/src/features/blocking, or motion-guide routing.
disable-model-invocation: true
---

# 白膜 Blockout Studio

## Scope

A third surface over the same `DramaEpisode` as 文案创作 (`zaolang-editor-drama`): a 3D previs of the episode — sets built from primitives, procedural mannequins, and a camera per script segment — that the author adjusts by chat or by dragging, then renders per segment as a **reference video** for generation. Gated by `blocking_studio_enabled` **and** `script_studio_enabled` (`app.domain.blocking.service.is_enabled`); `ScriptDetailResponse.blocking` is `null` while off. Desktop widths only (`md`+).

## Key Paths

| Path | Contents |
| --- | --- |
| `back/app/domain/blocking/vocabulary.py` | the closed preset vocabularies (actions, shot sizes, heights, sides, 15 camera moves, primitives…) and limits — one source for the Pydantic models/TS unions, the sanitizer and the prompt |
| `back/app/domain/blocking/segments.py` | `ordered_segments` (Python port of `orderedBreakpointKeys` — keys must agree with `front/src/features/script/script-breakpoint.ts`), duration estimates, `segment_source_hash`/`script_hash` |
| `back/app/domain/blocking/sanitize.py` | `sanitize_blocking` — the only writer's validator; forces sets/cast/segments to the script, completes partial replies from the previous version, fits durations to the target, carries or drops `camera_override`; `stale_segment_keys` |
| `back/app/domain/blocking/service.py` | state, three-phase turn stream, rebuild, `patch_manual` (409 on stale `base_version_no`, coalesces manual saves within 60s), settings |
| `back/app/agents/blocking_director.py` | `copy` slots `blocking_route` (JSON) and `blocking_derive` (streamed summary + fenced JSON) |
| `back/app/api/v1/blocking.py` | `/v1/scripts/{id}/blocking/turns` (SSE), `…/blocking:rebuild` (SSE), `PATCH …/blocking`, `PATCH …/blocking/settings`, `GET …/blocking/versions/{n}` |
| `back/app/domain/media/reference_roles.py` | the motion-guide directive/negatives prepended in `workflows/nodes._plan_enhancements` |
| `front/src/features/blocking/compiler/` | pure, deterministic document → `Timeline.sample(t)` (cast tracks, shot framing, move presets, overrides) — vitest-covered |
| `front/src/features/blocking/engine/` | plain three.js (no r3f): `player.ts`, `mannequin.ts` + `poses.ts` (FK pose table, sine gait), `stage.ts`, `editor.ts` (TransformControls) |
| `front/src/features/blocking/export/render-segment.ts` | segment → MP4 (same player, detached canvas, mediabunny) |
| `front/src/features/blocking/blocking-studio.tsx` | the page body: viewport (2/3) + `ScriptChatPanel` (1/3), transport, scrubber, shot picker, video actions |

## Invariants

1. **The model writes semantics, never animation.** Presets, anchors and shot grammar only; `compileBlocking` is the one place motion is computed, and the player and the exporter both sample it — so the exported clip matches what the author watched.
2. **Every write goes through `sanitize_blocking`** — model reply (`mode="llm"`), browser save and settings (`mode="manual"`). Links (`character_ref_id`) come from the script, never from the model or the browser.
3. **Segments are keyed exactly like breakpoints** (`{heading}#{ordinal}`); a kept-over segment keeps its *old* `source_hash` so staleness stays visible until it is re-staged. Staleness is computed server side only.
4. **A 白膜 turn edits the script only through `copywriter.stream_revise_script`** (phase `script`), and persists as `EpisodeScriptTurn(origin="blocking")` + one `EpisodeBlockingVersion`. A failed derive never blanks the blockout.
5. **Segment durations are whole seconds in [5, 15]** (`VIDEO_MAX_DURATION_SECONDS` once `video_options` is set; the shortest reference-capable model floor), fitted to `target_duration_seconds` or the script estimate.
6. **Render colours are fixed, not theme tokens** (`palette.ts`): a light and a dark theme must export the identical clip. Cast tags are DOM (CSS2D), so they never reach an exported frame and character images never need CORS.
7. **Motion guides route only to reference-to-video models** (`ProviderCapability.accepts_video_reference`, never an EDIT model); ordinary video references are unaffected. Validation requires `text_to_video`, input-reference mode, exactly one video reference.
8. **Three.js is lazy**: the engine and mediabunny load by dynamic `import()`; the studio page itself imports only the pure compiler.

## Verify

```bash
cd back && pytest tests/unit/test_blocking_segments.py tests/unit/test_blocking_sanitize.py tests/unit/test_motion_guide_routing.py tests/integration/test_blocking.py
cd front && npx vitest run src/features/blocking && npm run check:messages
```
