# Generation Jobs — asset pipeline & workflow graph reference

## Asset-kind axes

| Axis | Enum (`back/app/models/enums.py`) | Valid for | Values |
| --- | --- | --- | --- |
| image | `ImageAssetKind` → `GenerationParams.asset_kind` | `text_to_image`, `image_to_image` | `general`, `character`, `scene`, `cover` |
| video | `VideoAssetKind` → `GenerationParams.video_asset_kind` | the three video operations | `general`, `scene_video`, `character_action`, `transition_video`, `cover_video` |

1. At most one axis is non-`general` (`validate_generation_params` in `back/app/api/schemas/jobs.py`); `nodes._asset_axis(ctx)` returns `("image", kind)` / `("video", kind)` / `None`.
2. `submit()` resolves the template by `(operation, asset_kind)` using whichever axis is set; `general` on both → `defaults.default_graph`, any other kind → `defaults.asset_graph` (one shared shape for every non-general kind).
3. Other asset fields on `GenerationParams`: `target_character_id` / `target_scene_id` (write-back target; unset → auto-create a draft skill, `AssetOutputLinkConfig.auto_create_character` / `auto_create_scene`), `subject_name_hint` (≤60, names the auto-created skill; ignored with a target), `auto_attach_asset` (default `True`; `False` borrows refs without writing back). All ignored by non-image/video operations.

## Character views & per-view loop

1. `character_views` (`CharacterViewAngle`, ≤3, only with `asset_kind=character`) is canonicalized to front→side→back; unset = `[front]`.
2. One job, many outputs: `asset_output_advance` (after `quality_check`) appends `{asset_id, view}` to `ctx.state["asset_outputs"]` (`ASSET_OUTPUTS_STATE_KEY`), stashes the next view in `_current_character_view`, and loops to `asset_planning` via the `next` port (retry-kind edge); `done` → `asset_output_link`. Video kinds and scene/cover never loop.
3. Multi-output lands in `GenerationJob.output_asset_ids_json` / `GenerationJobResponse.output_asset_ids`; single-output jobs only fill the singular fields.
4. Pricing multiplies by `jobs_service.character_output_count` (`output_count` in `back/app/domain/credits/pricing.py`); time limits add `_IMAGE_EXTRA_VIEW` per extra view up to `_IMAGE_GENERATION_CAP` (`back/app/workers/tasks.py`).
5. Progress rescales per view (`nodes._scale_for_character_views`) so the bar doesn't restart each loop.

## `execute_asset_planning` rules (`back/app/workflows/nodes.py`)

1. Every entry resets `ctx.prompt` / `negative_prompt` to the originals (`_ORIGINAL_PROMPT_STATE_KEY`, `_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY`) so views don't inherit each other's text.
2. Character `side`/`back` pass: prompt hard-overridden by `_CHARACTER_COMPLETION_FIXED_PROMPTS` and `_CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT` merged — driven by the attached front reference, not caller text.
3. Character front (incl. single-view): keep caller prompt, append `_CHARACTER_SHEET_LAYOUT_SUFFIX`, then `_apply_character_visual_medium` (no medium named → photoreal + anime negative; named medium kept, opposite negative added). Completion passes skip the medium lock.
4. Then calls `planner.plan_asset` (image) or `planner.plan_video_asset` (video) and folds `prompt_enhancements` / `negative_prompt_suggestions` in. Planner briefs and view prompt text: see `zaolang-agent-gateway`.
5. `_planned_prompt` ignores the generic `planning` node's plan whenever `_asset_axis` is set — that plan is view-blind and runs once before the loop.
6. `asset_graph` seeds `planning.config.allow_followup_question = False` (clarify can't see asset kind/view); `default_graph` keeps it on. Live templates need a data migration to change (e.g. `back/alembic/versions/20260818_2000_disable_asset_planning_followup.py`).

## Write-back (`execute_asset_output_link`)

1. The only node that mutates something outside job/Work/Draft. No-op on `dry_run`, no outputs, no axis, or `auto_attach_asset=False`; never fails the job (logs and skips).
2. Character: first output appends to (or auto-creates) the character skill's `params_json["character"]["reference_assets"]`; later views reuse that same id. A stale `target_*_id` (deleted since) falls back to auto-create; character auto-create first reuses an owned same-name card (`find_owned_character_by_name` — titles are unique per owner, else 422). Scene: same against `params_json["scene"]["reference_assets"]` (no name reuse).
3. Video `character_action` → `characters_service.append_action_clip` (`action_clips`, never `reference_assets`; same-name reuse as above). `transition_video` / `cover_video` / image `cover` attach nowhere.
4. Stamps `GenerationJob.linked_character_id` / `linked_scene_id` (used by the script studio's jump-back). Copy nested `params_json` before mutating — see `zaolang-data-model`.

## Default graphs (`back/app/workflows/defaults.py`)

- `default_graph`: `safety → skill_context → planning → intent_router → route_score → provider_generate → quality_check → settle_success`; retry edges `provider_generate`/`quality_check` → `route_score`; `no_candidate` / `retries_exhausted` / `failed` → `fail`.
- `asset_graph`: same, plus `intent_router → asset_planning → route_score` and `quality_check → asset_output_advance → (next: asset_planning | done: asset_output_link) → settle_success`.
- `video_analysis_graph`: `safety → planning (allow_followup_question=False) → route_score → video_analysis_generate → settle_success`; no skill_context / intent_router / quality_check.
- Node types and config schemas: `back/app/workflows/registry.py`, `back/app/workflows/configs.py`.

## Video analysis

1. `execute_video_analysis_generate` mirrors `execute_provider_generate`'s routing/billing/cancel/retry skeleton but registers no `Asset`; output goes to `ctx.state["result_json"]` → `settle_success` → `GenerationJob.analysis_result_json`.
2. Full reserved credits are captured (not in the video prorating set of `settlement_credits`).
3. Frontend lists its own jobs via `GET /v1/generation-jobs?operation=video_analysis` (no `draft_id`); `front/src/features/video-analysis/api.ts`.
4. Upload purpose `video_analysis_source` (size cap in `back/app/storage/s3.py`; see `zaolang-media-assets`).
