---
name: zaolang-creation-library
description: CreationSkill library — templates, seeded catalogue, character/scene rosters stored as skills, draft→review→publish, paid unlock, @-mention apply. Use when editing skill_library/characters/scenes domains, /v1/skills|characters|scenes, the /skills plaza, or /create/characters|scenes.
---

# Creation Library

**Scope**: user-authored and seeded `CreationSkill` rows — prompt templates plus the character/scene rosters (same table, other `category`), their share/review/sell lifecycle, and studio apply.
Not here → `zaolang-admin-ops` (review, takedown), `zaolang-credits-billing` (unlock charges), `zaolang-agent-gateway` (agent_skills), `zaolang-data-model` (`sk_` ids), `zaolang-canvas` (workflow `variables`), `zaolang-generation-jobs` (`execute_skill_context`).

## Key Paths

| Path | What |
|---|---|
| `back/app/models/skill_library.py` | `CreationSkill`; partial unique index `uq_creation_skills_owner_character_title` |
| `back/app/domain/skill_library/service.py` | lifecycle, `list_public`/`list_mine`, `ensure_catalog_skills`, auto-matchers |
| `back/app/domain/skill_library/catalog.py` | `CATALOG`, `COVERS_PENDING`; JPEGs in sibling `seed_covers/` |
| `back/app/domain/skill_library/folding.py` | `TEMPLATE_FOLD_KEYS`, `RESERVED_TEMPLATE_KEYS`, `fold_params_prompt` |
| `back/app/domain/characters/service.py` | `CharacterView`, reference assets, `action_clips`, `publish_character`, `apply_character_refs` |
| `back/app/domain/scenes/service.py` | `SceneView`, `apply_scene_refs` |
| `back/app/api/v1/skills.py` | `/v1/skills*`: `/public`, CRUD, `/pricing`, `/publish`, `/withdraw`, `/unlock`, `/apply` |
| `back/app/api/v1/characters.py` | `/v1/characters*` + `reference-assets/{asset_id}`; `scenes.py` mirrors it |
| `front/src/app/[locale]/(site)/skills/page.tsx` | plaza; URL filters `contentType` × `category` × `access` |
| `front/src/components/skills/` | plaza grid/card, detail+unlock dialog, create/manage dialogs, `@` menu |
| `front/src/components/characters/character-library.tsx` | `/create/characters`; twin `scene-library.tsx` in `components/scenes/` |
| `front/src/lib/skill-mention.ts` | `isSkillMentionable`, `creationStudioHref`, `@Title` token helpers |
| `front/src/components/studio/use-applied-skills.tsx` | studio apply, `MAX_APPLIED_SKILLS`, `?skillId=` seed |

## Invariants

1. Characters/scenes are `CreationSkill` rows (`character`/`scene_asset`), payload at `params_json["character"|"scene"]`. Edit them only via `/v1/characters|scenes` — `PATCH /v1/skills/{id}` overwrites `params`/`category` wholesale.
2. Create → `DRAFT`/`PRIVATE`. `publish()` runs the `skill_moderation` gate, sets `PENDING_REVIEW`/`PUBLIC`, reopens the single queue row (subject `skill`); re-publish is a no-op. Public reads check `status == PUBLISHED` only — `service.py:get_usable`.
3. A content edit on a non-`DRAFT` row drops it to `DRAFT`/`PRIVATE` (all three services); `/pricing` never does. Only `withdraw()` closes the open queue item.
4. Characters publish only via `POST /v1/characters/{id}/publish` with `portrait_consent: true` (stamps `portrait_consent_at`); `/v1/skills/{id}/publish` rejects them. Scenes need no consent.
5. One character name per owner: DB index + `_require_unique_character_name` (422 on `name`). Scenes are not unique.
6. Paid: `access_credits > 0` needs `marketplace_enabled` and ≤ `max_access_credits` (`access.service.normalize_access_credits`). Detail `params` is `{}` until `viewer_unlocked` (owner/free/grant). `/unlock` honours `Idempotency-Key`.
7. `POST /apply` is the only usage counter (asserts unlocked). The plaza dialog never calls it; the studio `?skillId=` seed does. Server re-fold and auto-matchers (`apply_matching_format_skills`, `list_drama_candidates`) never count or charge.
8. Image-asset categories fold only `TEMPLATE_FOLD_KEYS`; `variables` never folds; empty `applicable_operations` = any, yet `isSkillMentionable` hides image-asset skills without declared ops.
9. `character_ids`/`scene_ids` (≤4 each) must be caller-owned; `jobs.service.submit` merges them before quoting into the shared 9-slot `reference_asset_ids`, explicit refs first. Others' marketplace stills pass via `asset_is_usable_skill_reference`.
10. Never mutate `params_json` in place — `_payload` returns copies, writes go through `_set_payload`; otherwise the UPDATE is silently skipped.
11. `reference_assets` ≤4 owned image/video; a character's non-`general` view replaces its old entry, scenes accumulate. `action_clips` (≤12 video) never reach `reference_asset_ids`.
12. Catalogue identity is `(owner, title)` (`CatalogSkill.key` isn't stored): `ensure_catalog_skills` plants `PUBLISHED` rows without review, never overwrites edits, only backfills a null cover. A retitle plants a new row.
13. `list_mine` and default `list_public` exclude `IMAGE_ASSET_SKILL_CATEGORIES`.

## Recipes

1. **Catalogue entry**: add a `CatalogSkill` (unique `key`+`title`; image rows use `_IMAGE_OPERATIONS`) → `seed_covers/<key>.jpg` or `COVERS_PENDING` → `make seed` (prod: `zaolang-remote-deploy`).
2. **Category**: enum in `back/app/models/enums.py` (+ `IMAGE_ASSET_SKILL_CATEGORIES` if asset-shaped) → plaza `CATEGORIES_BY_CONTENT_TYPE`/`CATEGORY_LABEL_KEY` → `skill-mention.ts` → `skillLibrary.category*` copy.
3. **Character field**: `CharacterView` property → service create/update → `back/app/api/schemas/characters.py` → `cd front && npm run gen:api` → `character-library.tsx`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_skill_library.py tests/integration/test_characters.py tests/integration/test_scenes.py tests/integration/test_access_marketplace.py tests/unit/test_characters_service.py tests/unit/test_scenes_service.py tests/unit/test_skill_library_catalog.py tests/unit/test_skill_context.py -q
cd front && npm run test -- src/lib/skill-mention.test.ts src/lib/plaza-skills.test.ts src/lib/characters.test.ts src/lib/scenes.test.ts
```
