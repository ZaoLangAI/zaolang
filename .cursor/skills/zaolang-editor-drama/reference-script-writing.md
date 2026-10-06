# Drama Editor — script writing reference

文案创作 (`/create/script`): idea → streamed scene-by-scene script → revision turns, then per-segment video generation.

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/script_writing/service.py` | `prepare_new_script`, `retry_new_script`, `prepare_turn`, `stream_new_script`/`stream_turn`, `update_links`, `update_content` (JSON `PATCH /v1/scripts/{id}`), `delete_script`, `_hydrate_source_idea` |
| `back/app/domain/script_writing/extract.py` | txt/docx/(best-effort) doc parsed locally, jpg/png via vision slot `script_extract`; ≤8MB, text ≤20 000 |
| `back/app/api/v1/scripts.py` | `/v1/scripts` routes, `_with_heartbeat`, `_replay_stream` |
| `back/app/api/schemas/script.py` | `ScriptDocument`, `ScriptDetailResponse` (incl. `blocking`, `source_idea`, `last_error`) |
| `back/app/api/schemas/shortform.py` | prompt-enhance schemas incl. `ScriptSegment` / `ScriptSegmentBlock` |
| `back/app/agents/copywriter.py` | `copy` agent slots `script_draft` / `script_revise` (`zaolang-agent-gateway`) |
| `front/src/features/script/script-landing.tsx` | 新建文案 dialog: typed idea or one uploaded file (`script-source-field.tsx` → `POST /v1/scripts/extract`) |
| `front/src/features/script/script-editor.tsx` | editor page: `script-chat-panel.tsx` (left) + `script-document-view.tsx` (right), batch toolbar |
| `front/src/features/script/script-breakpoint.ts` | breakpoint keys, locations, hrefs, video index (`orderedBreakpointKeys`, `resolveBreakpointHref`…) |
| `front/src/features/script/script-prompts.ts` | every prompt helper (`composeClipPrompt`, `breakpointSegmentPrompt`, `characterImagePrompt`…) |
| `front/src/features/script/script-clip-studio.tsx` | one-cut video studio at `/create/script/{episodeId}/clip?key=` |
| `front/src/features/script/script-link-picker.tsx` | 关联角色卡/场景卡 picker → `PATCH /v1/scripts/{id}/links`; 新建…卡 / 去创作 footer |
| `front/src/features/script/batch-plan.ts` | pure pending/bound computations (`pendingCharacters`, `pendingVideos`, `pendingDialogueLines`…) |
| `front/src/features/script/use-script-batch.ts` | batch runner, `BatchKind` characters/scenes/videos/audio, `quoteForBatch`, `submitJob`/`pollJob` (reused by 白膜) |
| `front/src/features/script/script-batch-dialog.tsx` | batch params + live quote before submit |
| `front/src/features/script/use-script-turn-stream.ts` | client for streamed turns (frames parsed by `front/src/lib/sse-post.ts`) |
| `front/src/features/script/create-stream-store.ts` | module singleton for the first-draft stream — outlives `ScriptLanding`, which navigates away once `episode_id` arrives |
| `front/src/features/script/stream-preview.ts` | `extractStreamingSummary`: hides the fenced JSON script while a turn streams (also used by 白膜) |
| `front/src/features/script/editable-text.tsx` | the app's one inline double-click edit → `PATCH /v1/scripts/{id}` |

## Data

1. A script is a normal `DramaEpisode`: `script_json` is always the latest turn's script; `EpisodeScriptTurn` is append-only history (`turn_no` unique per episode, `script_snapshot_json`, `thinking_text`, `origin` `script`|`blocking`). `GET …/turns/{turn_id}/snapshot` browses a version.
2. `prepare_new_script` with `seriesId` attaches to that drama series (must be accessible, `kind=drama`); without, mints a new `Series(kind=drama)` shell. Next number is computed in `season_number == 1`. Stores `source_idea` + `source_referenced_skill_ids_json` (user picks only, ≤5) and fires the `script` notification in the same transaction. The prompt's skill list is topped up to 5 by `skill_matcher` (`_topped_up_with_matches`, see `zaolang-agent-gateway`); matched ids are never stored.
3. `_hydrate_source_idea` back-fills an empty shell's idea from a nearby `script_draft` `AgentRun` so retry works without re-typing.
4. `script_writing.service._owned_episode` is really the accessible check (owner or active collaborator).
5. `delete_script`: 422 if `canonical_work_id`; runs `purge_unpublished_editor_graph`; never hard-deletes the `Series`. When the owner deletes the last episode of a still-uncurated shell (empty `target_platforms_json`, never through the series form), the series goes to the recycle bin via `trash_drama_series`. Dashboard series, already-trashed series and co-creator deletes leave the series untouched.
6. Extracted upload bytes are never stored as an `Asset`; the text lands in `source_idea`.

## Streaming

7. Model-driven writes — `POST /scripts`, `POST /scripts/{id}/retry`, `POST /scripts/{id}/turns` — return `SSE_STATUS_CODE` 202 `text/event-stream`: `start` (new script only), `delta`, `thinking`, then `complete` or `error`. Everything else is JSON.
8. Failure after headers is only `event: error` as the last frame. Streams use their own `session_scope()` (request `DbSession` is closed); every error path must `session.rollback()` or `PendingRollbackError` kills the stream without a closing frame.
9. `_with_heartbeat` emits `: heartbeat` comments every `_HEARTBEAT_INTERVAL_SECONDS` (12s) while idle; comments carry no `data:` and are dropped client-side. The hard ceiling is `STREAM_WALL_CLOCK_TIMEOUT_SECONDS` in `back/app/llm/client.py`.
10. `thinking` is best-effort (token-wise or one late burst); `complete` carries the full string, stored as `thinking_text`. Render with shared `LiveThinking`/`ThinkingDisclosure` (`front/src/components/ai/thinking-disclosure.tsx`; `front/src/features/script/thinking-paragraphs.ts` only re-exports `thinkingParagraphs`) — no script-specific renderer.
11. A retried request with the same idempotency key replays one `complete` frame (`_replay_stream`), never re-running the model.

## Breakpoints & clip studio

12. `breakpoint` blocks (建议切分) key segments as `{heading}#{ordinal}` (`breakpointKey`); the same keys drive 白膜 segments (`zaolang-blocking-studio`).
13. Split by concern: keys/locations/hrefs in `script-breakpoint.ts`; all prompt text in `script-prompts.ts`. New prompt helpers go in `script-prompts.ts`.
14. Breakpoint chip → `/create/script/{episodeId}/clip?key=` (id only, never `?prompt=`); bound drafts add `draftId` to resume history. Batch generation submits in memory and does not open the page.
15. Clip studio polish sends `script_segment` (heading + ≤60 blocks) to `POST /v1/generation/prompts/enhance`; the block union rejects `breakpoint` (a new cut would shift keys and orphan bound drafts). Two rounds: response `questions`, next request `question_answers` (≤8). Accept patches only that cut's block texts.
16. Submit composes `composeClipPrompt` into `params.prompt` and stores `link_episode_id`, `link_breakpoint_key`, `clip_user_prompt` on the draft.
17. Link picker writes `character_ref_id`/`ref_id` against the existing `/v1/characters`/`/v1/scenes` library. With nothing linked its 新建角色卡 / 新建场景卡 (`onCreate` in `script-document-view.tsx`) creates a text-only card from the script's character traits / scene heading + `scene` blocks and links it via `PATCH /v1/scripts/{id}/links`; once linked the footer offers 去创作 (the card's workspace). There is no image-studio jump-out or 返回文案创作 link-back any more (AC-8).

## Batch generation

18. `use-script-batch.ts` quotes, submits one item at a time, tracks each job, supports pause/resume, and stamps `link_episode_id` + `link_breakpoint_key` on every submit so results bind back. Audio (`audio_generation`) dubs dialogue lines per speaker: `voice-plan.ts` maps each speaker → the script character's linked card → the voice bound to its `look_id` look, else the card's default voice (overridable per speaker in the dialog, `speaker-voices.tsx`), sent as `voice_profile_id`; speakers without one use the batch's 通用音色 (`extra.voice`). `dubbedDialogueKeys` skips lines already voiced. 同步到角色库 on a linked character chip drafts the card's description / voice description from this script (`character-describe-dialog.tsx`).
19. `script-batch-dialog.tsx` quotes via `POST /v1/generation-jobs/quote:batch` (exact per-line sum, skipped for an empty batch). Quote/quoting/failed state and the effective voice (falls back to the roster's first) are derived during render from the settled request — no setState-in-effect.
20. Keep pending/bound logic pure in `batch-plan.ts` (vitest-covered).
