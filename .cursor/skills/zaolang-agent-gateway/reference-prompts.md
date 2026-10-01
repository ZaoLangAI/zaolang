# Agent Gateway — prompts reference

Copy coaches, asset-kind prompt rules, scene skill packs, follow-up questions. Script-writing slots → `zaolang-editor-drama`; 白膜 slots → `zaolang-blocking-studio`.

## Prompt resolution

- What runs is the published `AgentSkill` for `(agent, slot)` via `agent_skills.service.resolve_prompt`; module constants are only seed + fallback. Changing a constant does nothing in an env whose operator edited that prompt.
- `sync_seeded_copy_agent_prompts` (`back/app/scripts/seed.py`) republishes constants onto the seeded copy agents (role default + `enhance-character`/`enhance-scene`/`enhance-cover`, created by `ensure_default_enhance_asset_agents`) only while their draft still looks factory; custom wording is left alone.
- Copy requests choose an agent by `resolve_copy_agent_id` using `AgentProfile.default_for_asset_kind` (`character`/`scene`/`cover`, else the `copy` bucket).
- `SKILL_TEMPLATES` (`back/app/domain/agent_skills/templates.py`) seed the admin editor's "fill from template"; copy templates carry `asset_kind` so a dedicated agent only offers its own kind. Opening the editor never overwrites a published prompt.

## Copy coaches (`back/app/agents/copywriter.py`)

- Slots (`PROMPT_SLOTS["copy"]`): `suggest` (`SYSTEM_PROMPT`, work title/description/tags), `enhance`, `clarify`, `script_draft`/`script_revise` (streamed), `skill_match` (`skill_matcher`), plus 白膜 `blocking_route`/`blocking_derive`. Copy never returns a pass/fail verdict.
- `enhance` coaches: `ENHANCE_SYSTEM_PROMPT` (general) and per-kind `ENHANCE_SYSTEM_PROMPT_CHARACTER`/`_SCENE`/`_COVER`; video kinds use `_VIDEO_ENHANCE_SYSTEM_PROMPTS` (fallback dict only, no seeded profiles). All share `_ENHANCE_CONTRACT` for the JSON shape — add a first-class constant per kind, never a footnote on the generic coach, and never a new slot for a kind.
- Enhance success needs an enhance-shaped object (`ENHANCE_JSON_KEYS` = `prompt` + `detail_level`); the first `{...}` in a reasoning trace is often a decoy.
- `_sanitize_enhance_outcome` runs kind-specific repairs (below) and `_sanitize_script_segment` (clip-studio `script_segment`: rewrite block `text` in place; add/drop/retype/`breakpoint` → fall back to the request segment).
- Repairs **append a sentence**, never cut words mid-sentence (broken Chinese).

## Character sheet views (owner of this fact)

`character_view=front` → **one image, multi-panel sheet**: left full-body three-view (front/side/back), right face close-ups + fabric/accessory detail + colour palette, single plain background. `side`/`back` → single-view full body, **never** a sheet or collage. These must stay aligned or 「AI 润色」 undoes the planner:

| Place | Role |
|---|---|
| `back/app/agents/planner.py` `_ASSET_KIND_BRIEF`, `_CHARACTER_VIEW_BRIEF` | `asset_plan` slot guidance per kind/view |
| `back/app/domain/image_assets/prompt_builder.py` `CHARACTER_SHEET_LAYOUT_SUFFIX` | appended on a sheet pass (keeps caller's identity prompt; re-exported as `nodes._CHARACTER_SHEET_LAYOUT_SUFFIX`) |
| `back/app/domain/image_assets/prompt_builder.py` `CHARACTER_COMPLETION_FIXED_PROMPTS` | side/back pass prompt **replaced** by a fixed reference-driven prompt + anti-collage negative |
| `back/app/domain/image_assets/prompt_builder.py` `apply_visual_medium` | sheet/expression pass with no named medium gets a photoreal lock; named anime/photoreal kept |
| `back/app/agents/copywriter.py` `ENHANCE_SYSTEM_PROMPT_CHARACTER`, `restore_character_sheet_prompt` | coach + repair: missing `三视图`/`色板` or collapse markers → re-append `CHARACTER_SHEET_LAYOUT_SENTENCE` |
| `front/src/lib/characters.ts` `characterSheetPrompt` | library/script jump-out prompt sent to the image studio (web submits front only) |

## Character/scene preset vocabulary

`back/app/domain/image_assets/vocabulary.py` is the single source for expression (`CharacterExpression`) and scene `SceneLighting`/`SceneWeather`/`SceneState`/`ScenePeriod` presets: `Literal` + `get_args` tuple + `{label, prompt, negative}` per value (periods add `cues`/`pitfalls`). Prompt fragments state renderable facts (facial muscles, colour temperature, light direction, era fixtures), never a bare mood word. Adding a value: Literal → preset entry → `make openapi` → front label map + copy.

## Prompt builder (`back/app/domain/image_assets/prompt_builder.py`)

- `resolve_pass` → `AssetPass` (`character_sheet`/`character_completion`/`character_expressions`/`scene`/`other`; a scene variant set is one `scene` pass per variant); `compose` writes the pass's fixed text before the planner runs; `execute_asset_planning` passes `asset_pass` to `planner.plan_asset`.
- Expression pass: `EXPRESSION_IDENTITY_PREFIX` + caller identity + `expression_layout` (grid from `vocabulary.expression_grid`, one sentence per cell) + medium lock; never the sheet suffix. Per-expression negatives only for a single close-up (they contradict across cells).
- Outfit sheet with a reference: `OUTFIT_CHANGE_PREFIX` locks face/hair/body to reference 1.
- Scene: preset fragments + period cues (pitfalls → negative); with a reference, `SCENE_VARIANT_PREFIX` pins geometry to reference 1. 
- `sanitize_enhancements` (Python, survives a published `AgentSkill`): drops 三视图/设定图/色板/分栏 additions on expression/scene passes and other-period labels when `scene_period` is set.
- Polish: `PromptEnhanceRequest` carries `character_expressions` + `scene_*` → `PromptContext.asset_presets` → coach user message (`asset_presets` labels). With expressions, `_sanitize_enhance_outcome` runs `restore_expression_prompt` instead of `restore_character_sheet_prompt`.

## Reference legend

- At submit `back/app/domain/image_assets/reference_resolver.py:resolve` writes `params["reference_labels"]` (`asset_variants.service.entry_label`: `角色「林夏」·设定图`, `角色「林夏」·婚礼·设定图`, `场景「客厅」·主图`, `场景「客厅」·黄昏·机位`) for references belonging to the job's picked/targeted characters and scenes.
- `nodes._with_reference_legend` prefixes `prompt_builder.reference_legend` (`参考图说明：图1 是…；图2 是…`) onto the provider prompt only; it numbers generic image references (`ProviderReference.asset_id`, no `frame_type`) truncated to `ProviderCapability.max_image_references` (`media_endpoints._max_image_references`: DMXAPI image profile, AiHubMix `image_reference_cap` — gpt-image-2 edits = 1, minimax_v2/fal video caps) and stays silent when the cap is unknown, <2 images, first/last frames are present, or nothing is labelled.
- The GENERATING event logs `prompt` (with legend) and `base_prompt` (without); `fast_retry._resolved_prompt` reads `base_prompt` / `strip_reference_legend` so a retry never doubles it.

## Scene plates

- Rule (`_ASSET_KIND_BRIEF["scene"]`, `ENHANCE_SYSTEM_PROMPT_SCENE`): empty plate, no people/silhouettes, single camera, one continuous space, occlusion holds (a closed door stays closed), no split/alternative viewpoints, explicit era/region (or worldbuilding) and a fixed visual medium.
- Repairs: `restore_scene_plate_prompt`, `enforce_scene_plate_occlusion`, `enforce_scene_plate_medium`.

## Scene skill packs (`back/app/agents/scene_skills.py`)

- `SCENE_SPACE_SKILLS`: one checklist per space type (structure, fixtures, light, era/world cues, pitfalls). `anchor` decides the follow-up: real places ask `era_region`, invented ones `worldbuilding`.
- `resolve_scene_skill(prompt, answer)` prefers the author's `space_type` answer over keyword matching.
- The pack rides the enhance **user** message (`copywriter._enhance_user_prompt`), never the system prompt — a published `AgentSkill` would otherwise drop it.

## Follow-up questions (`back/app/agents/questions.py`)

- `sanitize_questions` is the one shape for `planner.clarify` (suspends a job), `copywriter.clarify` (pre-submit) and the scene coach's polish-time `questions`. Limits `MAX_QUESTIONS`/`MAX_OPTIONS`/`QUESTION_KINDS`.
- A choice question with no legal options is dropped, not repaired — an unanswerable required question would deadlock the studio's submit gate.

## Reference skills in polish

- `format` skills: rule text appended to `prompt` by Python (`skill_library.service.apply_matching_format_skills`), surfaced as `applied_format_skills`.
- `drama` skills: `skill_matcher.select_reference_skills` (cheap titles-only call) picks rows; the coach reads them as material (`referenced_skills`), nothing is appended. Video operations only (`VIDEO_OPERATIONS_FOR_ENHANCE`); any failure → empty list, polish proceeds.
- The route runs matching before opening the stream and emits a `matched` SSE frame first (`back/app/api/v1/prompts.py`).
