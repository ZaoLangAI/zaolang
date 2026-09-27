---
name: zaolang-discovery-search
description: Discovery — works browse/search (keyword + pgvector), similar works, tags, discover filters and Hero, search history, user style presets, curated style gallery. Use when changing search, feeds, tag/sort filters, embeddings, style presets or domain/style_gallery.
---

# Discovery & Search

**Scope**: making works findable (browse, search, similar, tags) and styles reusable (user `StylePreset`, platform `StyleGalleryEntry`).
Not here → `zaolang-domain-licensing-lineage` (visibility, publish), `zaolang-community` (rest of `community.py`).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/search/service.py` | `_visible_works`, `browse`, `search`, `similar_works`, `index_version`, `_apply_access_filter` |
| `back/app/models/search.py` | `WorkEmbedding`; `EMBEDDING_DIM` is the single dimension source |
| `back/app/api/v1/works.py` | `GET /v1/works` (`q`, `tag`, `remixable`, `access`, `semantic`, `sort`, cursor), `GET /v1/tags` |
| `back/app/domain/style_gallery/service.py` | Curated styles: `list_active` (by `sort_order`), admin CRUD, `get_usable`, `apply` counter |
| `back/app/api/v1/style_gallery.py`, `back/app/api/v1/admin/style_gallery.py` | Public list/detail/apply; admin CRUD |
| `back/app/api/v1/community.py` | `/v1/style-presets` (user presets: save, list, apply) |
| `front/src/app/[locale]/(site)/discover/page.tsx` | Discover wall + Hero; filters in URL (`?q`, `?tag`, `?sort`, `?access`) |
| `front/src/components/discover/` | `tag-filter.tsx`, Hero, fixed 16:9 grid (`INSPIRATION_COLUMNS`) |
| `front/src/lib/search-history.ts` | Top-bar recent queries in `localStorage` (8 max, deduped, per browser) |
| `front/src/lib/style-gallery.ts` | `styleGalleryLabel` — trilingual label by locale |
| `front/src/components/studio/style-gallery-dialog.tsx` | Apply a system style in the studio |

## Invariants

1. Every query starts from `_visible_works()` (`ACTIVE` + public) and filters in SQL — never fetch then filter.
2. `EmbeddingProvider` (`back/app/domain/search/embeddings.py`) is pluggable; the default is a deterministic hash, not a real model — say so in reports. Never import a concrete provider; tests use `set_provider`.
3. Changing `EMBEDDING_DIM` = migration + recompute every `WorkEmbedding`.
4. Hybrid `search` = keyword score × `KEYWORD_WEIGHT` + vector × `VECTOR_WEIGHT`. Keep keyword weight higher so a title hit outranks a semantic-only hit.
5. Publishing calls `index_version` synchronously — skip it and the work is unsearchable.
6. Tags are `Tag` + `WorkTag` rows, never a string array.
7. `access=free|paid` means `PUBLIC_REMIXABLE` with `access_credits` = 0 / > 0 — both exclude view-only works.
8. API default is `sort=recent`; only the web discover page defaults to `popular`. Don't change the API default.
9. The Hero is its own `sort=popular` request, ignoring the wall's query; the wall never drops Hero tiles.
10. Jobs carry `style_gallery_id`; `execute_skill_context` in `back/app/workflows/nodes.py` folds the entry into the prompt. `StylePreset.params_json` mirrors generation params — keep save and apply in sync. Don't mix gallery entries into user presets.

## Recipes

**Add a sort**: `browse` sort key with `id` tiebreaker for a stable cursor → `sort` Literal in `works.py` → web sort tabs + iOS `WorksSort` + `discover.sort*` keys.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_discovery.py tests/unit/test_style_gallery.py -v
```
