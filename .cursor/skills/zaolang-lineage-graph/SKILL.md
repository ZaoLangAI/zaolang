---
name: zaolang-lineage-graph
description: Web lineage-graph UI — dagre layout drawn as hand-rolled SVG, ancestors + descendants in one view, tombstone placeholders, keyboard nodes, and the per-edge version diff panel. Use when changing front/src/components/lineage or the work-page lineage strip.
---

# Lineage Graph (web)

**Scope**: rendering a work's lineage (`GET /v1/works/{id}/lineage`) and the selected version's diff.
Not here → `zaolang-domain-licensing-lineage` (edges, tombstones, remix rules), `zaolang-ios-client` (iOS graph).

## Key Paths

| Path | What |
|---|---|
| `front/src/components/lineage/lineage-graph.tsx` | dagre layout + SVG; `NODE_WIDTH`/`NODE_HEIGHT`; `GraphNode.direction` + `current` |
| `front/src/components/lineage/lineage-explorer.tsx` | Fetches lineage; graph on top, selected node's `VersionDiffPanel` below (always stacked) |
| `front/src/components/lineage/lineage-dialog.tsx` | Full-screen wrapper; the discover inspiration dialog also embeds the explorer |
| `front/src/components/lineage/version-diff-panel.tsx` | `GET /v1/work-versions/{childVersionId}/diff` |
| `front/src/components/work/lineage-strip.tsx` | Compact ancestor chain on the work page |
| `back/app/api/v1/works.py` | `/lineage` (`depth` default 4, max 8) and `/diff` endpoints |

## Invariants

1. dagre computes layout; nodes are hand-drawn SVG using theme tokens. No graph/canvas library.
2. Both directions render at once. `direction === 'root'` is the oldest ancestor (or the focused work when it has none, `--amber` "original" badge); the focused work is `current: true` (`--primary` badge). `root` ≠ "the work on this page".
3. Tombstoned nodes render as placeholders (`IconTombstone`), are not focusable and never open detail.
4. Interactive nodes: `tabIndex=0`, Enter/Space select, visible focus ring.
5. Depth is bounded by the API's `depth` query (default 4, max 8); don't expand further client-side. Large graphs → truncate server-side, not virtualize.
6. Diff compares one edge: the selected node's `work_version_id` vs its parent. Root has no parent → `diffEmpty`, not an error. Kinds `added` / `removed` / `modified` stay distinct. Values are withheld unless `can_remix` holds for the child work.
7. The graph is read-only; remixing still goes through `assert_remixable`.

## Recipes

**Add node info**: extend the backend lineage node → `make openapi` → types in `front/src/lib/api/types.ts` follow → adjust node size constants.

**Add a node state**: new field next to `direction`/`tombstone`; never overload `tombstone`.

## Verify

```bash
make test-front
make test-a11y && make qa-visual
```
