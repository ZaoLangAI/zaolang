---
name: zaolang-creation-library
description: CreationSkill library — templates, seeded catalogue, character/scene rosters stored as skills, draft→review→publish, paid unlock, @-mention apply. Use when editing skill_library/characters/scenes domains, /v1/skills|characters|scenes, the /skills plaza, or /create/characters|scenes.
---

# Creation Library

**Scope**: user-authored and seeded `CreationSkill` rows — prompt templates plus the character/scene rosters (same table, other `category`), their share/review/sell lifecycle, and studio apply.
Not here → `zaolang-admin-ops` (review, takedown), `zaolang-credits-billing` (unlock charges), `zaolang-agent-gateway` (agent_skills), `zaolang-data-model` (`sk_` ids), `zaolang-canvas` (workflow `variables`), `zaolang-generation-jobs` (`execute_skill_context`, job-output write-back into rosters).

## Key Paths

| Path | What |
|---|---|
| `back/app/models/skill_library.py` | `CreationSkill`; partial unique index `uq_creation_skills_owner_character_title` |
| `back/app/domain/skill_library/service.py` | lifecycle, `list_public`/`list_mine`, `ensure_catalog_skills`, auto-matchers |
| `back/app/domain/skill_library/catalog.py` | `CATALOG`, `COVERS_PENDING`; JPEGs in sibling `seed_covers/` |
| `back/app/domain/skill_library/folding.py` | `TEMPLATE_FOLD_KEYS`, `RESERVED_TEMPLATE_KEYS`, `fold_params_prompt` |
| `back/app/domain/characters/service.py` | `CharacterView`, reference assets, `action_clips`, `publish_character`, `apply_character_refs` |
| `back/app/domain/asset_variants/service.py` | looks/variants + entries (`SkillAssetVariant`/`SkillAssetEntry` in `back/app/models/skill_library.py`): `project`, `sync_mirror`, `add_entry`, `set_anchor`, `set_members`, `moderation_texts`; design `docs/asset-variants-p1.md` |
| `back/app/domain/scenes/service.py` | `SceneView`, `apply_scene_refs` |
| `back/app/api/v1/skills.py` | `/v1/skills*`: `/public`, CRUD, `/pricing`, `/publish`, `/withdraw`, `/unlock`, `/apply` |
| `back/app/api/v1/characters.py` | `/v1/characters*` + `reference-assets/{asset_id}`; `scenes.py` mirrors it. Responses carry `looks`/`variants` + `anchor_entry_id` (`back/app/presenters/asset_variants.py`) |
| `back/app/api/v1/asset_variants.py` | `/v1/characters/{id}/looks…`, `/v1/scenes/{id}/variants…`, `…/entries/{entry_id}` (+ `:anchor`); owner-only 404, every write `withdraw_after_edit` |
| `front/src/app/[locale]/(site)/skills/page.tsx` | plaza; URL filters `contentType` × `category` × `access` |
| `front/src/components/skills/` | plaza grid/card, detail+unlock dialog, create/manage dialogs, `@` menu |
| `front/src/components/characters/character-library.tsx` | `/create/characters`; twin `scene-library.tsx` in `components/scenes/`; both open `front/src/components/library/asset-variants-sheet.tsx` (looks / variants + entries) |
| `front/src/lib/skill-mention.ts` | `isSkillMentionable`, `creationStudioHref`, `@Title` token helpers |
| `front/src/components/studio/use-applied-skills.tsx` | studio apply, `MAX_APPLIED_SKILLS`, `?skillId=` seed |

## Invariants

1. Characters/scenes are `CreationSkill` rows (`character`/`scene_asset`), payload at `params_json["character"|"scene"]`. Edit them only via `/v1/characters|scenes` (+ looks/variants routes): `/v1/skills` create/edit 422s on both categories. The skill detail (`/v1/skills/{id}`) strips the `reference_assets` mirror from `params` and, once unlocked, returns signed `asset_variants` + `anchor_asset_id` instead.
2. Create → `DRAFT`/`PRIVATE`. `publish()` runs the `skill_moderation` gate, sets `PENDING_REVIEW`/`PUBLIC`, reopens the single queue row (subject `skill`); re-publish is a no-op. Public reads check `status == PUBLISHED` only — `service.py:get_usable`.
3. A content edit on a non-`DRAFT` row drops it to `DRAFT`/`PRIVATE` and closes the open queue item (`withdrawn_by_owner`), same as `withdraw()` — all three services go through `service.py:withdraw_after_edit`; `/pricing` never does.
4. Characters publish only via `POST /v1/characters/{id}/publish` with `portrait_consent: true` (stamps `portrait_consent_at`); `/v1/skills/{id}/publish` rejects them. Scenes need no consent.
5. One character name per owner: DB index + `_require_unique_character_name` (422 on `name`). Scenes are not unique.
6. Paid: `access_credits > 0` needs `marketplace_enabled` and ≤ `max_access_credits` (`access.service.normalize_access_credits`). Detail `params` is `{}` until `viewer_unlocked` (owner/free/grant). `/unlock` honours `Idempotency-Key`.
7. `POST /apply` is the only usage counter (asserts unlocked). The plaza dialog never calls it; the studio `?skillId=` seed does. Server re-fold and auto-matchers (`apply_matching_format_skills`, `list_drama_candidates`) never count or charge — so the matchers only take free rows owned by the catalogue account (`_planted_catalog_rows`), never a user's same-titled skill.
8. Image-asset categories fold only `TEMPLATE_FOLD_KEYS`; `variables` never folds; empty `applicable_operations` = any, yet `isSkillMentionable` hides image-asset skills without declared ops.
9. `character_ids`/`scene_ids` (≤4 each) must be caller-owned. `back/app/domain/image_assets/reference_resolver.py:resolve` (called by `jobs.service.submit` before quoting) merges them into the shared 9-slot `reference_asset_ids`, explicit refs first: each card contributes its `character_ref_selection`/`scene_ref_selection` item — `variant_id` (that look's default subset), `asset_ids` (the card's own, or that look's when both are given), else 422 — or `asset_variants.service.default_subset` (character: the anchor when it is the default look's, or any look's `identity_portrait`, then the look's sheet/views front→side→back, ≤3; scene: the variant's master then shots, else the card's anchor, ≤2). Defaults are re-ranked by `asset_variants.service.ReferenceHints` (P2-7) from `reference_shot_size` / `reference_emotion`, else the shot size in the prompt's 「镜头：」 line (`blocking.camera_language.parse_camera_text`): a close shot leads with the identity portrait and an expression sheet showing the emotion, a wide one with sheet + views, a close scene shot with its shots before the master; explicit `asset_ids` are never reordered. It also borrows the target look's sheet for an expression job with no reference, the target's approved identity portrait (`asset_variants.service.identity_portrait`) for any other character job with no reference, and writes `reference_labels` (`asset_variants.service.entry_label`, e.g. `角色「林夏」·婚礼·设定图`). An unlocked published card's approved entries are usable references (`skill_library.service.asset_is_usable_skill_reference`); others' covers likewise.
10. Never mutate `params_json` in place — `_payload` returns copies, writes go through `_set_payload`; otherwise the UPDATE is silently skipped.
11. Reference images live in `skill_asset_variants` (looks/variants: one `is_default` per card, unique name, ≤12 looks per character card; scene cards are uncapped) and `skill_asset_entries` (`entry_type`, `view`, `label`, `status`, one `is_anchor` per card; ≤24 approved per look, ≤120 approved per character card (scene cards: per-variant cap only) — over a cap is 422, nothing is evicted; candidates are uncapped and kept until the owner deletes them). Both CASCADE with the skill and entries with their asset; a composite FK keeps an entry on its own card's look. `CharacterView`/`SceneView.reference_assets` is `asset_variants.service.project` (anchor first; a non-default look's entries carry its name as `label`), mirrored into `params_json[...]["reference_assets"]` by `sync_mirror` after every change — the JSON is a read-only mirror, never write it directly. The legacy `(view, label)` calls translate: a non-`表情·` label is the look name, front → `character_sheet` (one per look; the default look's first becomes the anchor), `establishing` → the variant's `master`. `action_clips` (≤12 video) stay in JSON and never reach `reference_asset_ids`.
12. Catalogue identity is `(owner, title)` (`CatalogSkill.key` isn't stored); owner = `catalog.CATALOG_OWNER_HANDLE` (`zaolang_studio`) for `make seed`, `app.scripts.ensure_catalog` and the `catalog_owner` test fixture. `ensure_catalog_skills` plants `PUBLISHED` rows unreviewed, never overwrites edits, only backfills a null cover; a retitle plants a new row.
13. `list_mine` and default `list_public` exclude `IMAGE_ASSET_SKILL_CATEGORIES`.
14. Candidate / approved (`AssetEntryStatus`): a job's write-back files into a filled slot as a `candidate` (`asset_variants.service.file_generated`); a manual upload or legacy edit still approves and replaces. `approve_entry` (`POST …/entries/{id}:approve`, or PATCH `status=approved`) swaps the slot — the displaced entry becomes a candidate and hands over the anchor. Only approved entries can be the anchor (a candidate anchor or demoting the anchor is 422). Candidates appear only in the owner's `looks`/`variants`; `project`, the mirror, `asset_ids`, `default_subset` and the skill detail (`variant_views(approved_only=True)`) use approved entries, and `set_members` leaves candidates alone. An identity portrait (`character_portrait` job, `append_reference_asset(portrait=True)`) is always filed in the default look; once approved it takes the anchor from no anchor or a sheet, never from another portrait (`prefer_portrait_anchor`).
15. Scene variant matrix (`POST /v1/scenes/{id}/variants:matrix`, `back/app/api/v1/scene_matrix.py` + `back/app/domain/scenes/matrix.py`): ≤4 values per axis, ≤12 cells per request; `dry_run` (default) returns each cell's status (`new` / `exists` = approved master / `candidate`) and the exact total (`quote_for` × new cells, balance + monthly cap like `quote:batch`). A submit refuses up front when the total does not fit, counts one `generation_submit` hit per job, then runs the ordinary submit per new cell (single-image `scene_*` presets + `target_scene_id`, per-cell idempotency key `{key[:100]}:{sha1(cell)[:12]}`); write-back files each image under the variant matching its presets.

## Recipes

1. **Catalogue entry**: add a `CatalogSkill` (unique `key`+`title`; image rows use `_IMAGE_OPERATIONS`) → `seed_covers/<key>.jpg` or `COVERS_PENDING` → `make seed` (prod: `zaolang-remote-deploy`).
2. **Category** (string column, no migration): enum in `back/app/models/enums.py` (+ `IMAGE_ASSET_SKILL_CATEGORIES`) → `make openapi` → every front copy (plaza `CATEGORIES_BY_CONTENT_TYPE`; `grep -rn 'CATEGORIES\b\|CATEGORY_LABEL_KEY' front/src`) → `skillLibrary.category*` copy.
3. **Character field**: `CharacterView` property → service create/update → `back/app/api/schemas/characters.py` → `make openapi` → `character-library.tsx`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_skill_library.py tests/integration/test_characters.py tests/integration/test_scenes.py tests/integration/test_access_marketplace.py tests/unit/test_characters_service.py tests/unit/test_scenes_service.py tests/unit/test_skill_library_catalog.py tests/unit/test_ensure_catalog.py tests/unit/test_skill_context.py tests/unit/test_skill_matcher.py -q
cd front && npm run test -- src/lib/skill-mention.test.ts src/lib/plaza-skills.test.ts src/lib/characters.test.ts src/lib/scenes.test.ts
```
