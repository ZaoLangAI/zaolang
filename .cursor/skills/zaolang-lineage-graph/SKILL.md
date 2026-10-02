---
name: zaolang-lineage-graph
description: Web lineage-graph UI — dagre layout drawn as hand-rolled SVG, ancestors + descendants in one view, tombstone/private placeholders, keyboard nodes, and the per-edge version diff panel. Use when changing front/src/components/lineage, the work-page lineage strip, or the /lineage and /diff endpoints' shape.
---

# Lineage Graph (web)

**Scope**: rendering a work's lineage (`GET /v1/works/{id}/lineage`) and the selected version's diff (`GET /v1/work-versions/{childVersionId}/diff`).
Not here → `zaolang-domain-licensing-lineage` (edges, tombstones, remix rules), `zaolang-ios-client` (iOS graph).

## Key Paths

| Path | What |
|---|---|
| `front/src/components/lineage/lineage-graph.tsx` | `layout()` (dagre, `rankdir: 'LR'`) + SVG; `NODE_WIDTH`/`NODE_HEIGHT`; `GraphNode.direction` + `current`; `truncated` notice |
| `front/src/components/lineage/lineage-explorer.tsx` | Fetches lineage on demand; graph on top, selected node's `VersionDiffPanel` below (always stacked) |
| `front/src/components/lineage/lineage-dialog.tsx` | Dialog wrapper (work page); `front/src/components/discover/inspiration-dialog.tsx` embeds the explorer directly |
| `front/src/components/lineage/version-diff-panel.tsx` | Diff table, changed rows only, `classify()` |
| `front/src/components/work/lineage-strip.tsx` | Compact chain (last 3 ancestors + descendant count); lazy `LineageDialog` via `next/dynamic` |
| `back/app/api/v1/works.py` | `get_lineage` (`depth` default 4, max 8), `version_diff`, `_ancestors` |
| `back/app/domain/lineage/service.py` | `build_tree`, `_node_for_version` (masking) |

## Invariants

1. dagre computes layout; nodes are hand-drawn SVG using theme tokens. No graph/canvas library. Entrance animation (`loadAnime`) is skipped under `useReducedMotion` and keyed on `graphSignature` so reselecting doesn't replay it.
2. Both directions render at once, left → right, ancestors oldest-first. `direction === 'root'` is the oldest ancestor (or the focused work when it has none, `--amber` "original" badge); the focused work is `current: true` (`--primary` badge). `root` ≠ "the work on this page" (the API's `root` field *is* the focused work).
3. `is_tombstone` = `not can_view` for this viewer: tombstoned, hidden **and** private nodes are all masked (title/cover blanked, author credit from the edge snapshot kept) in both `_node_for_version` and `_ancestors`. They render as placeholders (`IconTombstone`), are not focusable and never open detail.
4. Interactive nodes: `tabIndex=0`, Enter/Space select, visible focus ring.
5. `depth` bounds only the descendant tree; ancestors walk up to `MAX_TRAVERSAL_DEPTH`. `truncated` / `total_descendants` tell the UI what was cut — truncate server-side, don't expand or virtualize client-side.
6. Diff compares one edge: the selected node's `work_version_id` vs its parent. Root has no parent (404) → `diffEmpty`, not an error. Both works must pass `assert_viewable`; title + param values are `null` unless `can_remix` holds for the child work (`changed` is still accurate). Kinds `added` / `removed` / `modified` are derived client-side from empty vs non-empty values and stay distinct.
7. The graph is read-only; remixing still goes through `assert_remixable`.

## Recipes

**Add node info**: extend `LineageNode` (service) + `LineageNodeResponse`/`LineageAncestor` → `make openapi` → types in `front/src/lib/api/types.ts` follow → adjust node size constants. Mask it when `is_tombstone`.

**Add a node state**: new field next to `direction`/`tombstone`; never overload `tombstone`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_lineage_visibility.py tests/integration/test_version_diff.py tests/integration/test_consumer_admin_role_visibility.py -v
make test-front
make test-a11y && make qa-visual
```
