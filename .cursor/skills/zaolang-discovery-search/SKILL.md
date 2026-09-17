---
name: zaolang-discovery-search
description: Discovery and reuse — a pluggable EmbeddingProvider + pgvector similar works, hybrid keyword/semantic search, the tag system, discover-page inspiration-wall sorting (recent/popular/remixed), user StylePresets, and the curated platform StyleGalleryEntry. Use when changing search, browse feeds, tag filters, inspiration-wall sort, embeddings, vector similarity, style presets, or the system style gallery.
disable-model-invocation: true
---

# Discovery & Reuse

## Scope

Make works findable (browse, search, similar-work recommendations) and make parameters reusable (tags, user style presets, the curated system style gallery).

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/domain/search/service.py` | `browse` / `search` / `similar_works` / `index_version` / `_visible_works` |
| `back/app/domain/search/embeddings.py` | the `EmbeddingProvider` abstraction, `DeterministicEmbeddingProvider`, `get_provider` / `set_provider` / `embed` |
| `back/app/models/search.py` | `WorkEmbedding` (pgvector `Vector(EMBEDDING_DIM)` column); `EMBEDDING_DIM = 256` is the single source of truth that `DeterministicEmbeddingProvider.dimension` and the migration both read |
| `back/app/models/works.py` | `Tag` / `WorkTag` / `StylePreset` (a user's distilled shortcut parameters from a work, optionally shareable) |
| `back/app/models/style_gallery.py` | `StyleGalleryEntry` (platform-curated system styles, written by admin operators, shared by the consumer inspiration wall and the studio dialog) |
| `back/app/api/v1/works.py` | `GET /v1/works` browse/search (`q`, `tag`, `remixable`, `access=free|paid|all`, `semantic`, `sort=recent|popular|remixed`, cursor); `access` is applied in SQL by `search.service._apply_access_filter` — `free` = `PUBLIC_REMIXABLE` with `access_credits == 0`, `paid` = `PUBLIC_REMIXABLE` with `access_credits > 0`, so both implicitly exclude view-only works; `GET /v1/tags` lists the normalized `Tag` entities the web `TagFilter` renders |
| `back/app/api/v1/style_gallery.py` | public style list / detail / `/apply` counter |
| `front/src/app/[locale]/(site)/discover/page.tsx`, `front/src/components/discover/tag-filter.tsx` | `/` redirects to the discover page; the inspiration wall's `TagFilter` chips + `DiscoverSort` (`popular`/`recent`/`remixed` — that order, matching the page default — rendered as `aria-current` underline tabs rather than chips, URL `?sort=`) + `DiscoverAccess` (`free`/`paid`/`all`, URL `?access=`) chips, all URL-encoded so a filtered view is shareable. The wall itself is a **fixed 16:9 grid** (`inspiration-skeleton.tsx`'s `INSPIRATION_COLUMNS` is a `grid`, every tile `aspect-video`), not a masonry — the variable-height machinery (`inspiration-aspect.ts` and its `TILE_RATIO_SAMPLES`) was deleted, so don't reintroduce per-tile aspect measurement |
| `front/src/components/work/reusable-params.tsx` | one-click parameter reuse |
| `front/src/components/studio/style-gallery-dialog.tsx`, `front/src/components/create/inspiration-recommendations.tsx` | applying a system style; the job carries `style_gallery_id`, and `skill_context` re-folds it server-side into `prompt_suffix` |

## Invariants

1. **Visibility filtering happens in SQL**: every query starts from `_visible_works()` (only `ACTIVE` and non-`PRIVATE`). **Never query first and filter after** — that lets filtered-out rows count toward page size, leaking both existence and total counts.
2. **Tombstoned and hidden works never appear in search results**, though they remain reachable via the lineage graph (see `zaolang-domain-licensing-lineage`).
3. **`EmbeddingProvider` stays pluggable**: the gateway has **no embedding model**; the default implementation is a local deterministic hash-based vector. Its purpose is "the interface and pipeline work end-to-end," not "search quality meets a bar" — say so plainly in any delivery report. Tests inject via `set_provider`; domain code must never `import` a concrete implementation.
4. **Changing vector dimensionality is a breaking change**: `WorkEmbedding`'s column dimension, its migration, and every existing row must be recomputed together — there's no incremental path.
5. **Hybrid search has a fixed order**: keyword hits first, semantic results supplement, then dedupe and merge — never let semantic results push an exact title match down.
6. **Publishing writes the index synchronously**: `index_version` is step 6 of the eight-step publish flow — skip it and the new work becomes unsearchable.
7. **Tags are normalized entities**: `Tag` is unique, `WorkTag` is the join table. Never store tags as a string array on the work.
8. **The discover-page Hero ignores the wall's entire query**: the wall reads `?q=` / `?tag=` / `?sort=` / `?access=` (default `sort=popular`, omitted from the URL at its default); the Hero is a separate `GET /v1/works?sort=popular&limit=6` and never forwards those params, so "本期精选" does not become a search, a tag, a price slice, or "most recent." The wall shows its full first page — it does **not** drop the Hero's leading tiles, even when both sides happen to be popularity-ranked (a short catalogue would otherwise empty "最热"). The create-page inspiration wall is the system style gallery, ordered by `sort_order` — a separate concern, don't conflate the two. iOS has the same three sort options but the wall defaults to `recent`; its Hero is already an independent popular request.
9. **`popular` is a web-page default, not an API default.** `GET /v1/works` (`api/v1/works.py`) and `search.service.browse` both default `sort="recent"`; only `discover/page.tsx` substitutes `popular` when `?sort=` is absent (and iOS keeps `recent`). A client that omits `sort` therefore gets newest-first — don't "fix" the API default to match the web page, it would silently reorder iOS, MCP and any raw caller.

## Extension Points

- **Swap in a real embedding model**: implement an `EmbeddingProvider` subclass → register it via `set_provider` (or select by config) → handle the dimension-change migration → recompute every `WorkEmbedding`. Domain and API layers need no changes.
- **Add a sort dimension**: change `browse`'s sort key (the cursor must be **stable and unique** — append `id` as a tiebreaker) → `GET /v1/works?sort=` → the web `DiscoverSort` chip and iOS's `WorksSort` menu (trilingual `discover.sort*`). Web filters/sorts must be shareable (encoded in the URL).
- **Add a filter**: filter condition → API parameter → keep `TagFilter` / `DiscoverSort` and the URL query in sync; render the sort bar even with no tags selected.
- **Extend style presets**: `StylePreset.params_json` shares its shape with generation parameters — add a field to both the "save preset" and "apply preset" paths together. `StyleGalleryEntry` is a separate table with its own admin CRUD — don't write the operations catalogue into user presets; the job's identity field is `style_gallery_id`, not the retired `style_preset_id`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_discovery.py -v
```

Manual path: `make seed` publishes no works, so first publish two or three works with distinct titles and tags (or create them with `tests/factories.make_work` in an integration test). Then on `/discover`, searching a word from one title should hit that work; switching to "recent" should put `sort=recent` in the URL while featured stays skewed popular; a work's "similar works" should not be empty; tagging a work should make it findable by that tag filter; making a work private should remove it from search immediately.
