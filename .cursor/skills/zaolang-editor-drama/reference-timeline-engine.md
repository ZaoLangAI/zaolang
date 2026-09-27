# Drama Editor — timeline engine reference

Engine, sync, render/export, leases, analysis, MCP and AI planning for `/studio-editor/{cutId}`.

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/editor/commands.py` | `validate_batch`, apply, allowlists (`EFFECT_TYPES`, `ANIMATABLE_PROPERTIES`, `PROPERTY_RANGES`, `EASING_TYPES`, `TRANSITION_TYPES`…) |
| `back/app/domain/editor/time.py` | `TICKS_PER_SECOND`, `MAX_COMMANDS_PER_BATCH` 100, `MAX_TRACKS_PER_KIND` 16, 5000 elements / 5MB caps |
| `back/app/domain/editor/document.py` | canonical schema; `canonicalize()` normalises tracks (`order`/`label`/`muted`) on read |
| `back/app/domain/editor/exports.py` | `queue_exports`, `claim_next`, `heartbeat`, `complete_export`, `reclaim_stale_exports`, `delete_export`, bind helpers |
| `back/app/domain/editor/analysis.py` | ffprobe `ANALYZER` and ASR `ASR_ANALYZER = "whisper-asr"` on `MediaAnalysis` |
| `front/src/features/editor/engine/canonical.ts` | client mirror of command apply (`applyBatch`, `deepCopyElement`) |
| `front/src/features/editor/engine/ports.ts` | `EditCommand` TS union |
| `front/src/features/editor/engine/compositor.ts` | `resolveFrame`, `resolveOverlap`, `resolveAudioLayers`, `layerVolumeAt`, `composeFrame`, `aiLabelRect` |
| `front/src/features/editor/engine/export-runner.ts` | browser export: mediabunny (dynamic import), `renderMixedAudio`, `aigcMetadataTags` |
| `front/src/features/editor/engine/` | also `audio-mixer.ts` (preview audio), `caption-layout.ts`, `effects.ts`, `wasm-compositor.ts`, `animation.ts`, `export-precheck.ts` |
| `front/src/features/editor/drama-editor.tsx` | local-first apply + serial sync queue, `withPredictedIds` |
| `front/src/features/editor/actions.ts` | `EditorActions` — one verb surface for toolbar, shortcuts, panels |
| `front/src/features/editor/studio/` | shell: `studio-shell.tsx` (`useEditorShortcuts`) + `shortcuts-dialog.tsx` (keep in step), media library, properties panel |
| `front/src/features/editor/timeline/` | `geometry.ts` (pure: zoom, timecode, snapping), `timeline.tsx`, `ruler.tsx`, `toolbar.tsx`, `dnd.ts` |
| `front/src/features/editor/transcript-review-panel.tsx` | the only path from a transcript to `insert_caption` commands |

## Commands & document

1. Three places define a command: `commands.py` (authority), `canonical.ts` (local apply), `ports.ts` (type). There is no separate JSON schema — change all three together.
2. `validate_batch` forbids generic path updates (`"path"` key or `update_property`). `set_keyframe.property` is a closed set with bounded `PROPERTY_RANGES`; add a property by hand on both sides — never accept caller paths.
3. `volume` keyframes use the `set_clip_volume` range 0–200 000 millipercent. Keyframes are coarse points; `resolveNumberAtTime` (`engine/animation.ts`) interpolates and holds edges.
4. Tracks: only `video`/`audio` (`TRACK_KINDS_ADDABLE`) can be added/removed; caption/overlay tracks are singletons; `remove_track` refuses the last of a kind or a non-empty track. Clip/caption inserts and cross-track moves check `track.kind`.
5. Stickers are `insert_clip` with `element_type: "sticker"` (`ELEMENT_TYPES_ADDABLE`) — no sticker command, track or provider.
6. Effects: `EFFECT_TYPES` = blur/brightness/contrast/saturate/grayscale, masks rect/ellipse. Only `blur` has a WASM shader (`wasm-compositor.ts:applyBlur`; the vendored `third_party/opencut-classic/rust/crates/effects/src/pipeline.rs` registers only `gaussian-blur`); the rest and masks are Canvas2D (`effects.ts`). Add an effect only if a shader is verified registered or it is CSS-filter-expressible.
7. Copies must deep-copy in-place-mutated fields: `effects` and `animations.channels` (`_deep_copy_element`/`_split_element`, `deepCopyElement`). Any new field mutated in place by its own command needs the same.
8. Split clears the new inner edge: left half keeps `transition_in`, right keeps `transition_out`.
9. Transitions live on one clip's `transition_in`/`transition_out` (`crossfade`|`dip_to_black`), `duration_ticks` ≤ the element's own duration. Blending happens only where same-track clips overlap: `resolveOverlap` picks outgoing `transition_out` else incoming `transition_in`; neither → newer clip wins. `dip_to_black` never yields a `transitionLayer`.
10. `duplicate_elements` is the only copy primitive (Ctrl+D, paste, AI). Paste = duplicate with `delta_ticks = playhead − min(start)`; the clipboard stores ids (`clipboardIds`), not snapshots.
11. Markers are document-level (`document["markers"]`), `MAX_MARKERS` 200, label ≤120; no render semantics.
12. Revisions are immutable snapshots; schema changes are absorbed by `canonicalize()` normalisers, not migrations.

## Client sync

13. `apply()` runs `applyBatch` locally, renders, then queues; `pump` sends one batch at a time chaining `expected_revision_id`. Server doc is adopted only when the queue drains. Any failure (409 included) clears the queue → `recoverFromConflict` → reload; no client merge.
14. `withPredictedIds` fills `element_id`/`track_id`/`marker_id`/`new_element_id(s)`; the server validates their uniqueness. New element-creating commands must accept an optional client id.
15. Local apply passes an empty `knownAssets` set; the server owns asset-ownership checks. `undo`/`redo`/restore/plan-apply `await flush()` first.
16. `CutRevisionResponse.asset_meta` (`RevisionAssetMeta`: duration, width, height, mime, media type) lets the client build assets without guessing.

## Render, audio, captions, export

17. Preview, export and precheck all draw through `composeFrame`; picture uses the topmost non-muted video track with an active clip.
18. `resolveAudioLayers` = every non-muted audio track's clip + the visible video's own sound. Preview: `AudioMixer` schedules buffers. Export: `renderMixedAudio` (`OfflineAudioContext`); `addAudioTrack` must precede `output.start()`, so `documentHasAudibleContent` decides up front.
19. Gain is 0–200% (`MAX_LAYER_VOLUME = 2`, `layerVolumeAt`); never clamp to 1. Keyframed volume exports via `setValueCurveAtTime(volumeCurve(...))`. Speed shifts pitch (no time-stretch).
20. Captions: `layoutCaptionLines` — CJK per char, Latin per word, kinsoku, ≤2 lines, `FONT_SCALES` down to 0.8 then 「…」.
21. Every export writes `aigcMetadataTags` (AIGC JSON, `ContentProducer`) before `start()`; the visible 「AI 生成」 pill is `ExportRenderOptions.aiLabel`, not part of `VariantSpec`, not drawn in preview. `complete_export` records unsigned provenance once per asset — never claim C2PA.
22. Export precheck (`export-precheck.ts`) samples 5 ticks through `resolveFrame` for `blank_frame`/`clip_off_canvas`.
23. Variants: `create_variants` hashes a spec from the shortform profile (30 fps, `max_duration_ticks`) and dedups per revision by `spec_hash`.

## Leases, exports, beat

24. Edit lease: `leases.require_write_lease` per write; expired/foreign → `LeaseHeld`. Losing the lease degrades to read-only.
25. Export lease: `queue_exports` creates `queued` rows; `POST /v1/editor-exports:claim` needs `capabilities.chrome_or_edge` (`BrowserRequired`) and sets a 45s `lease_expires_at`; each heartbeat (`encoding|uploading|verifying`) renews it; terminal rows raise `OperationTerminal`.
26. `reclaim_stale_exports` fails lapsed rows with `code="stale_lease"` (the blob lived only in that tab) — run by beat `expire_stale_editor_exports` and inline in `queue_exports`. Beat also runs `expire_editor_leases`, `expire_orphan_editor_uploads` (queue `webhook_reconcile`).
27. `DELETE /v1/editor-exports/{id}`: owner, terminal only, 422 if published or stamped on a `WorkVersion`; unbinds the draft, keeps asset/variant. `ensure-bound-draft` recovers a finished export onto a draft.
28. `create_cut_from_asset` maps the unique-name violation to `Conflict("该集已有同名剪辑。")`. `PATCH /v1/episode-cuts/{id}` renames only.

## Analysis & transcription

29. Analysis and ASR run on Celery queue `media_analysis` (`run_media_analysis`, `run_editor_transcription`); `make dev-worker` must list it. Dedup by `(asset_id, analyzer, analyzer_version)`.
30. ASR credentials come from enabled `llm_providers` media endpoints serving `audio_generation` (`_resolve_asr_endpoint`), not the agent router.
31. `GET /v1/editor-operations/{id}` checks ownership only on the `man_` branch.
32. AI may enqueue transcription (`editor.request_transcription`) but nothing auto-commits captions; a human confirms in `transcript-review-panel.tsx`. Keep that gap.

## AI planning & MCP

33. `POST /v1/episode-cuts/{cut_id}/edit-plans` streams SSE (`iter_agent_sse`, `thinking`/`delta`/`complete`/`error`); `FLAG_AI` + `_owned_cut` are checked before the stream opens (plain 404). `apply` goes through revision CAS; a stale base is rejected.
34. MCP `project_id` = `Series.id`. Tool scopes: `drama:read`, `editor:read`, `editor:write`, `editor:export` (`TOOLS`). `apply_edit_plan` works without any open tab.

## Product path

Job succeeds → 进入剪辑 (`createCutFromJob`, new tab) → `/studio-editor/{cutId}` → variants + sequential browser export → `ensure-bound-draft` / `bind-editor-export` → standard `/publish/{draftId}` flow. Gold standard: `/create/short/gold-sample` (`gold-sample.tsx`, `createIndependentEngines`) on real Chrome/Edge.
