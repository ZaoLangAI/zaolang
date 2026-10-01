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
| `back/app/api/v1/characters.py` | `/v1/characters*` + `reference-assets/{asset_id}`; `scenes.py` mirrors it |
| `front/src/app/[locale]/(site)/skills/page.tsx` | plaza; URL filters `contentType` × `category` × `access` |
| `front/src/components/skills/` | plaza grid/card, detail+unlock dialog, create/manage dialogs, `@` menu |
| `front/src/components/characters/character-library.tsx` | `/create/characters`; twin `scene-library.tsx` in `components/scenes/` |
| `front/src/lib/skill-mention.ts` | `isSkillMentionable`, `creationStudioHref`, `@Title` token helpers |
| `front/src/components/studio/use-applied-skills.tsx` | studio apply, `MAX_APPLIED_SKILLS`, `?skillId=` seed |

## Invariants

1. Characters/scenes are `CreationSkill` rows (`character`/`scene_asset`), payload at `params_json["character"|"scene"]`. Edit them only via `/v1/characters|scenes`: `/v1/skills` create/edit 422s on characters, but a scene `PATCH`ed there gets `params`/`category` overwritten wholesale.
2. Create → `DRAFT`/`PRIVATE`. `publish()` runs the `skill_moderation` gate, sets `PENDING_REVIEW`/`PUBLIC`, reopens the single queue row (subject `skill`); re-publish is a no-op. Public reads check `status == PUBLISHED` only — `service.py:get_usable`.
3. A content edit on a non-`DRAFT` row drops it to `DRAFT`/`PRIVATE` and closes the open queue item (`withdrawn_by_owner`), same as `withdraw()` — all three services go through `service.py:withdraw_after_edit`; `/pricing` never does.
4. Characters publish only via `POST /v1/characters/{id}/publish` with `portrait_consent: true` (stamps `portrait_consent_at`); `/v1/skills/{id}/publish` rejects them. Scenes need no consent.
5. One character name per owner: DB index + `_require_unique_character_name` (422 on `name`). Scenes are not unique.
6. Paid: `access_credits > 0` needs `marketplace_enabled` and ≤ `max_access_credits` (`access.service.normalize_access_credits`). Detail `params` is `{}` until `viewer_unlocked` (owner/free/grant). `/unlock` honours `Idempotency-Key`.
7. `POST /apply` is the only usage counter (asserts unlocked). The plaza dialog never calls it; the studio `?skillId=` seed does. Server re-fold and auto-matchers (`apply_matching_format_skills`, `list_drama_candidates`) never count or charge — so the matchers only take free rows owned by the catalogue account (`_planted_catalog_rows`), never a user's same-titled skill.
8. Image-asset categories fold only `TEMPLATE_FOLD_KEYS`; `variables` never folds; empty `applicable_operations` = any, yet `isSkillMentionable` hides image-asset skills without declared ops.
9. `character_ids`/`scene_ids` (≤4 each) must be caller-owned; `jobs.service.submit` merges them before quoting into the shared 9-slot `reference_asset_ids`, explicit refs first. Each contributes `character_ref_selection`/`scene_ref_selection` when picked (ids must be that card's own refs, else 422), else its default subset — `characters.service.default_reference_asset_ids` (unlabelled front/side/back, ≤3) / `scenes.service.default_reference_asset_ids` (master plate + next unlabelled, ≤2). Labelled outfits/expressions/variants only go in when picked. Others' marketplace stills pass via `asset_is_usable_skill_reference`.
10. Never mutate `params_json` in place — `_payload` returns copies, writes go through `_set_payload`; otherwise the UPDATE is silently skipped.
11. Reference images live in `skill_asset_variants` (looks/variants: one `is_default` per card, unique name, ≤12) and `skill_asset_entries` (`entry_type`, `view`, `label`, `status`, one `is_anchor` per card; ≤24 per look, ≤120 per card — over a cap is 422, nothing is evicted). Both CASCADE with the skill and entries with their asset; a composite FK keeps an entry on its own card's look. `CharacterView`/`SceneView.reference_assets` is `asset_variants.service.project` (anchor first; a non-default look's entries carry its name as `label`), mirrored into `params_json[...]["reference_assets"]` by `sync_mirror` after every change — the JSON is a read-only mirror, never write it directly. The legacy `(view, label)` calls translate: a non-`表情·` label is the look name, front → `character_sheet` (one per look; the default look's first becomes the anchor), `establishing` → the variant's `master`. `action_clips` (≤12 video) stay in JSON and never reach `reference_asset_ids`.
12. Catalogue identity is `(owner, title)` (`CatalogSkill.key` isn't stored); owner = `catalog.CATALOG_OWNER_HANDLE` (`zaolang_studio`) for `make seed`, `app.scripts.ensure_catalog` and the `catalog_owner` test fixture. `ensure_catalog_skills` plants `PUBLISHED` rows unreviewed, never overwrites edits, only backfills a null cover; a retitle plants a new row.
13. `list_mine` and default `list_public` exclude `IMAGE_ASSET_SKILL_CATEGORIES`.

## Recipes

1. **Catalogue entry**: add a `CatalogSkill` (unique `key`+`title`; image rows use `_IMAGE_OPERATIONS`) → `seed_covers/<key>.jpg` or `COVERS_PENDING` → `make seed` (prod: `zaolang-remote-deploy`).
2. **Category** (string column, no migration): enum in `back/app/models/enums.py` (+ `IMAGE_ASSET_SKILL_CATEGORIES`) → `make openapi` → every front copy (plaza `CATEGORIES_BY_CONTENT_TYPE`; `grep -rn 'CATEGORIES\b\|CATEGORY_LABEL_KEY' front/src`) → `skillLibrary.category*` copy.
3. **Character field**: `CharacterView` property → service create/update → `back/app/api/schemas/characters.py` → `make openapi` → `character-library.tsx`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_skill_library.py tests/integration/test_characters.py tests/integration/test_scenes.py tests/integration/test_access_marketplace.py tests/unit/test_characters_service.py tests/unit/test_scenes_service.py tests/unit/test_skill_library_catalog.py tests/unit/test_ensure_catalog.py tests/unit/test_skill_context.py tests/unit/test_skill_matcher.py -q
cd front && npm run test -- src/lib/skill-mention.test.ts src/lib/plaza-skills.test.ts src/lib/characters.test.ts src/lib/scenes.test.ts
```
