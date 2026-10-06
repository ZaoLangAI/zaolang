# Generation Jobs — asset pipeline & workflow graph reference

## Asset-kind axes

| Axis | Enum (`back/app/models/enums.py`) | Valid for | Values |
| --- | --- | --- | --- |
| image | `ImageAssetKind` → `GenerationParams.asset_kind` | `text_to_image`, `image_to_image` | `general` (canvas Agent only), `character`, `scene`, `prop` (AC-4: `target_prop_id`, `prop_state`, write-back `_link_prop_output`); `cover` is read-only history (AC-8: `GenerationParams` refuses it, `ensure_default_templates` seeds no cover template, the planner/copy coaches dropped it). Consumer image jobs need a library kind: `api/v1/jobs.py:_require_asset_image_kind` 422s `IMAGE_ASSET_KIND_REQUIRED` in quote, quote:batch, submit, retry, promote — never in `jobs_service.submit` |
| video | `VideoAssetKind` → `GenerationParams.video_asset_kind` | the three video operations | `general`, `scene_video`, `character_action`, `transition_video`, `cover_video` |

1. At most one axis is non-`general` (`validate_generation_params` in `back/app/api/schemas/jobs.py`); `nodes._asset_axis(ctx)` returns `("image", kind)` / `("video", kind)` / `None`.
2. `submit()` resolves the template by `(operation, asset_kind)` using whichever axis is set; `general` on both → `defaults.default_graph`, any other kind → `defaults.asset_graph` (one shared shape for every non-general kind).
3. Preset fields (`GenerationParams._asset_presets_scoped_to_their_kind`, vocab in `back/app/domain/image_assets/vocabulary.py`): character-only `character_expressions` (1–9 → one composite image; views must stay `[front]`; needs ≥1 reference at submit) and `character_outfit_label`; scene-only `scene_lighting`/`scene_weather`/`scene_state`/`scene_period` (one image) or `scene_variants` (2–4 combos → one image each, mutually exclusive with the single presets). `character_ref_selection` picks per-character reference images (each `character_id` must be in `character_ids`). `reference_labels` is server-written — `submit()` drops a client value. Pricing uses `jobs_service.requested_output_count` (views, or variant count).
4. Other asset fields on `GenerationParams`: `target_character_id` / `target_scene_id` (write-back target; unset → auto-create a draft skill, `AssetOutputLinkConfig.auto_create_character` / `auto_create_scene`), `subject_name_hint` (≤60, names the auto-created skill; ignored with a target), `auto_attach_asset` (default `True`; `False` borrows refs without writing back). All ignored by non-image/video operations.

## Character views & per-view loop

1. `character_views` (`CharacterViewAngle`, ≤3, only with `asset_kind=character`) is canonicalized to front→side→back; unset = `[front]`.
2. One job, many outputs: `asset_output_advance` (after `quality_check`) appends `{asset_id, view}` to `ctx.state["asset_outputs"]` (`ASSET_OUTPUTS_STATE_KEY`), stashes the next view in `_current_character_view`, and loops to `asset_planning` via the `next` port (retry-kind edge); `done` → `asset_output_link`. Video kinds and scene/cover never loop.
3. Multi-output lands in `GenerationJob.output_asset_ids_json` / `GenerationJobResponse.output_asset_ids`; single-output jobs only fill the singular fields.
4. Pricing multiplies by `jobs_service.character_output_count` (`output_count` in `back/app/domain/credits/pricing.py`); time limits add `_IMAGE_EXTRA_VIEW` per extra view up to `_IMAGE_GENERATION_CAP` (`back/app/workers/tasks.py`).
5. Progress rescales per view (`nodes._scale_for_character_views`) so the bar doesn't restart each loop.
6. Each later view gets a fresh routing budget: `nodes._start_next_asset_pass` resets `route_attempts`/`tried_providers`/`failure_code`. `attempt_seq` keeps counting across the job and is what `attempt_number` (→ object key `output_{n}.png`) uses, so views never overwrite each other; both counters ride `_provider_checkpoint`/`_input_checkpoint`.
   A side/back pass puts this job's own front output first in `reference_asset_ids` and the legend (`nodes._chain_front_reference`, label `CHAINED_FRONT_LABEL`); every pass restarts from the submitted references (`_ORIGINAL_REFERENCES_STATE_KEY`).
7. The quality retry cap (`quality.MAX_QUALITY_RETRIES`) is per pass: `execute_quality_check` passes `route_attempts`, not the job-wide `attempt_number`, so a later view or variant can still be regenerated once.
8. Partial delivery: when a later pass fails (route budget spent, or quality fail with no retry) after earlier passes recorded outputs, `execute_fail` hands off to `nodes._finish_partial_asset_job` — no graph edge, so templates need no data migration. It attaches the delivered outputs with the graph's own `asset_output_link` config (`WorkflowContext.node_configs`, set by `WorkflowRunner._walk`), settles per image via `settlement_credits(requested_outputs, delivered_outputs)`, and ends `SUCCEEDED` with `delivered_outputs`/`requested_outputs`/`failure_code` in the event payload. `GenerationJobResponse.requested_outputs` lets clients show "已交付 d/N" (`front/src/components/job/job-outputs.ts:partialDelivery`). An asset job never stays on `/jobs/{id}` (it redirects to its card workspace, which shows only the images), so the job notification carries it: `notifications.push.partial_delivery` adds `delivered_outputs`/`requested_outputs`/`refunded_credits` to the payload and `notification-format.ts` picks `jobSucceededPartial`.

## `execute_asset_planning` rules (`back/app/workflows/nodes.py`)

1. Every entry resets `ctx.prompt` / `negative_prompt` to the originals (`_ORIGINAL_PROMPT_STATE_KEY`, `_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY`) so views don't inherit each other's text.
2. Then `prompt_builder.compose` for the pass from `prompt_builder.resolve_pass` (side/back completion override, sheet + outfit, expression grid, scene presets — a variant set's current combo via `_pass_params`) — rules in `zaolang-agent-gateway` › `reference-prompts.md` › Prompt builder. Completion passes skip the medium lock.
3. A scene variant set's current pass index lives in `SCENE_VARIANT_STATE_KEY`.
4. Then calls `planner.plan_asset` (image) or `planner.plan_video_asset` (video) and folds `prompt_enhancements` / `negative_prompt_suggestions` in. Planner briefs and view prompt text: see `zaolang-agent-gateway`.
5. `_planned_prompt` ignores the generic `planning` node's plan whenever `_asset_axis` is set — that plan is view-blind and runs once before the loop.
6. `asset_graph` seeds `planning.config.allow_followup_question = False` (clarify can't see asset kind/view); `default_graph` keeps it on. Live templates need a data migration to change (e.g. `back/alembic/versions/20260818_2000_disable_asset_planning_followup.py`).

## Scene variant sets

1. `scene_variants` (2–4) loop like character views: one SCENE pass per variant. `nodes._pass_params` folds the current combo (`SCENE_VARIANT_STATE_KEY`) into `scene_*` for the builder/planner/sanitizer; `asset_output_advance` records `{asset_id, view, label}` per pass and loops via `next`. Any single-output model serves them.
2. Priced `unit × N` (`requested_output_count`); each pass captures in full like a multi-view job; time limit adds `_IMAGE_EXTRA_VIEW` per extra variant (capped). Progress rescales per pass (`_pass_position`).
3. Not a provider group call: a live check showed DMXAPI Seedream returns one image for `sequential_image_generation` `max_images=2`, so `ImageModelProfile.max_group_outputs` stays 1.

## Multi-angle jobs (`camera_poses`, AC-2)

1. `camera_poses` (≤8 `CameraPose`, `asset_kind` character/scene, needs `source_entry_id` or a reference; exclusive with views/expressions/portrait/outfit/edit/in_scene/`scene_variants`) loop like views: one pass per pose (`CAMERA_POSE_STATE_KEY`). Each pass `execute_asset_planning` writes the pose to `ctx.params["extra"]["camera_pose"]` (`_set_pass_camera_pose`, cleared otherwise; a client value is dropped by `reference_resolver.resolve`) — the router prefers `camera_control` routes for it — and composes `AssetPass.CAMERA_ORBIT` (identity / scene lock + `camera.to_prompt_phrase`, no planner additions).
2. `camera_from_sheet` (the source is a composite sheet): pass 1 is the 0° front figure drawn out of the sheet (`AssetPass.SHEET_FRONT_FIGURE`, no pose → never the camera route); later passes put that output first (`_chain_orbit_front`, label `CHAINED_ORBIT_FRONT_LABEL`).
3. `asset_output_advance` records `{asset_id, view, camera}` per pass; a legacy side/back view pass records its pose too (`camera.from_view`) and writes it to `extra` so a camera route could serve it. Write-back passes `camera` → a character `view` (coarse view from the pose) or a scene `shot` (`reverse` at 180°, `detail` when close), one slot per pose.
4. Priced `unit × N` (`requested_output_count(camera_poses=…)`); time limit adds `_IMAGE_EXTRA_VIEW` per extra pose (capped); progress rescales (`_pass_position`).

## Scene panoramas (`scene_panorama`, AC-7)

1. `GenerationParams.scene_panorama` needs `asset_kind=scene` + `target_scene_id`, excludes derive (`source_entry_id`/`asset_edit`/output overrides), `camera_poses` and `scene_variants`, and forces `aspect_ratio="2:1"` (single-image `scene_*` presets still apply). Priced as one image. The API is the only place that forces the ratio — domain callers never set the flag.
2. `reference_resolver._borrow_scene_reference`: with no reference, borrow only a master plate (the target variant's, else the default's, else a master anchor); no master → text-only.
3. Routing: `router._request_constraint_failure` drops every route whose `ProviderCapability.exact_image_aspect_ratios` lacks `2:1` (`panorama_size_not_supported`) — today only DMXAPI Seedream (`zaolang-agent-gateway` › providers).
4. `AssetPass.SCENE_PANORAMA` composes the plate (`zaolang-agent-gateway` › `reference-prompts.md`); write-back (`_derive_filing`) files it as the variant's `panorama` entry (a candidate when one is approved), never master or anchor.

## Write-back (`execute_asset_output_link`)

1. The only node that mutates something outside job/Work/Draft. No-op on `dry_run`, no outputs, no axis, or `auto_attach_asset=False`; never fails the job (logs and skips).
2. Character: first output appends to (or auto-creates) the character skill's `params_json["character"]["reference_assets"]`; later views reuse that same id. A stale `target_*_id` (deleted since) falls back to auto-create; character auto-create first reuses an owned same-name card (`find_owned_character_by_name` — titles are unique per owner, else 422). Scene: same against `params_json["scene"]["reference_assets"]` (no name reuse).
3. Video `character_action` → `characters_service.append_action_clip` (`action_clips`, never `reference_assets`; same-name reuse as above). `transition_video` / `cover_video` / image `cover` attach nowhere.
4. Filing target (`filing` dict → `append_reference_asset`): `target_variant_id` (a look of the target card; stale → fallback), else the outfit label / the pass's scene presets (variant matched by `presets_json`, named by `scene_preset_label`), else the default; expressions → `expression_sheet` with `expressions_json`; every entry records `source_job_id`. A non-default scene variant's first image becomes its `master`.
   Write-back passes `generated=True`, so it files through `asset_variants.service.file_generated`: an image whose slot (`slot_mates`: the card's identity portrait, a look's front sheet, each single view, each expression set, a variant's master) already holds an approved entry — or that would exceed the approved caps — is filed as a `candidate` beside it; nothing is replaced or skipped. `GenerationJobResponse.candidate_entries` counts them for the studio's "去定稿" hint.
5. Labels: `_character_output_label` (outfit name, or `表情·冷笑/隐忍…` for an expression image, filed as view `general`) and `_scene_output_label` (the entry's own variant label, else the presets' combined label). Each output attaches in its own savepoint — one failure never drops the rest.
6. Stamps `GenerationJob.linked_character_id` / `linked_scene_id` (used by the script studio's jump-back). Copy nested `params_json` before mutating — see `zaolang-data-model`.

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
