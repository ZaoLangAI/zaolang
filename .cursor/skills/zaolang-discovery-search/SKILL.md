---
name: zaolang-discovery-search
description: Discovery — works browse/search (keyword + pgvector), similar works, tags, discover wall filters and Hero, search history, user style presets, curated style gallery. Use when changing search, feeds, tag/sort/access filters, embeddings, style presets or domain/style_gallery.
---

# Discovery & Search

**Scope**: making works findable (browse, search, similar, tags) and styles reusable (user `StylePreset`, platform `StyleGalleryEntry`).
Not here → `zaolang-domain-licensing-lineage` (visibility, publish), `zaolang-community` (rest of `community.py`), `zaolang-admin-ops` (style gallery console), `zaolang-frontend-ui` (studio layout).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/search/service.py` | `_visible_works`, `browse`, `search`, `similar_works`, `index_version`, `_apply_access_filter`; `KEYWORD_WEIGHT`/`VECTOR_WEIGHT`/`CANDIDATE_MULTIPLIER` |
| `back/app/models/search.py` | `WorkEmbedding` (HNSW cosine, unique per version+provider); `EMBEDDING_DIM` is the single dimension source |
| `back/app/api/v1/works.py` | `GET /v1/works` (`q`, `tag`, `remixable`, `access`, `semantic`, `sort`, cursor), `/works/{id}/similar`, `GET /v1/tags` (by `usage_count`) |
| `back/app/domain/style_gallery/service.py` | Curated styles: `list_active` (by `sort_order`), admin CRUD, `get_usable` (inactive → 404), `apply` counter |
| `back/app/api/v1/style_gallery.py`, `back/app/api/v1/admin/style_gallery.py` | Public list/detail/apply; admin CRUD + cover upload |
| `back/app/api/v1/community.py` | `/v1/style-presets` (user presets: save, list `mine`/public, apply) |
| `front/src/app/[locale]/(site)/discover/page.tsx` | Discover wall + Hero; filters in URL (`?q`, `?tag`, `?sort`, `?access`) |
| `front/src/components/discover/` | `tag-filter.tsx` (`TagFilter`/`DiscoverSort`/`DiscoverAccess`), `hero-carousel.tsx`, `inspiration-masonry.tsx` (cursor paging, `MAX_AUTO_LOAD_PAGES`), 16:9 grid `INSPIRATION_COLUMNS` in `inspiration-skeleton.tsx`, `inspiration-dialog.tsx` (preview) |
| `front/src/lib/search-history.ts` | Recent queries for `front/src/components/layout/search-box.tsx`, `localStorage` (8 max, deduped, per browser) |
| `front/src/lib/style-gallery.ts` | `styleGalleryLabel` — trilingual label by locale |
| `front/src/components/studio/style-gallery-dialog.tsx` | System style picker (fetches only while open); hosted by `useStyleAndSkillPicker` in `style-and-skill-picker.tsx`, which also lists presets |

## Invariants

1. Every query starts from `_visible_works()` (`ACTIVE` + public) and filters in SQL — never fetch then filter.
2. `EmbeddingProvider` (`back/app/domain/search/embeddings.py`) is pluggable; the default is a deterministic hash, not a real model — say so in reports. Never import a concrete provider; tests use `set_provider`.
3. Changing `EMBEDDING_DIM` = migration + recompute every `WorkEmbedding`.
4. Hybrid `search` = keyword score × `KEYWORD_WEIGHT` + vector × `VECTOR_WEIGHT` over `limit × CANDIDATE_MULTIPLIER` candidates. Keep keyword weight higher so a title hit outranks a semantic-only hit.
5. With `q`, `/v1/works` ignores `tag`/`sort` and returns no `next_cursor` (ranked in memory). Only `browse` pages: cursor = opaque work id anchor with `id` tiebreak; unknown anchor → empty page, never page one.
6. Publishing calls `index_version` synchronously (title + description + prompt + `style_tags`) — skip it and the work is unsearchable and has no `similar_works`.
7. Tags are `Tag` + `WorkTag` rows, never a string array.
8. `access=free|paid` means `PUBLIC_REMIXABLE` with `access_credits` = 0 / > 0 — both exclude view-only works.
9. API default is `sort=recent`; only the web discover page defaults to `popular`. Don't change the API default.
10. The Hero is its own `sort=popular` request, ignoring the wall's filters; the wall never drops Hero tiles.
11. Jobs carry `style_gallery_id`; `execute_skill_context` in `back/app/workflows/nodes.py` folds the entry (via `get_usable`) into the prompt. `StylePreset.params_json` mirrors generation params — keep save and apply in sync. Saving a preset from someone else's version needs its reusable params + an unlock. Don't mix gallery entries into user presets.
12. Mount the studio params panel (which owns `StyleGalleryDialog`) once: `GenerationStudioShell` drops it from the aside while the mobile sheet is open (`panelInAside`); both mounted = two dialogs below `lg`.

## Recipes

**Add a sort**: `browse` sort key with `id` tiebreaker for a stable cursor → `sort` Literal in `works.py` → web sort tabs + iOS `WorksSort` + `discover.sort*` keys.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_discovery.py tests/unit/test_style_gallery.py tests/unit/test_skill_context.py tests/integration/test_admin_style_gallery.py tests/integration/test_community.py -v
```
