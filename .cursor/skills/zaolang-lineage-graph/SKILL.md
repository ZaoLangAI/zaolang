---
name: zaolang-lineage-graph
description: Lineage-graph frontend — dagre-laid-out, hand-drawn SVG tree DAG, bidirectional tracing (ancestors / descendants), tombstone nodes, parent/child version parameter diff panel. Use when changing the lineage graph, its layout, tombstone rendering, node interaction, or the version parameter diff panel.
disable-model-invocation: true
---

# Lineage Graph

## Scope

Make "where this work came from, and who remixed it further" understandable in one screen. The tree DAG with bidirectional tracing (ancestors / descendants) is a complete feature, not an optional enhancement.

## Key Paths

| File | Contents |
| --- | --- |
| `front/src/components/lineage/lineage-graph.tsx` | dagre layout + hand-drawn SVG; `NODE_WIDTH/HEIGHT`, `GraphNode.direction` (`ancestor` / `root` / `descendant`) plus the independent `GraphNode.current` flag — `root` is the chain's origin (the oldest ancestor, or the focused work itself when it has none), `current: true` is the work the page is about |
| `front/src/components/lineage/lineage-explorer.tsx` | `LineageExplorer` — fetches `GET /v1/works/{workId}/lineage` on demand, renders `LineageGraph` on top and, once one node is selected, its title + "open work" button + `VersionDiffPanel` underneath (always stacked, never side-by-side). Shared by `lineage-dialog.tsx` and the discover preview (`components/discover/inspiration-dialog.tsx`, `dynamic()`-imported) |
| `front/src/components/lineage/lineage-dialog.tsx` | full-screen viewer container around `LineageExplorer` |
| `front/src/components/lineage/version-diff-panel.tsx` | `VersionDiffPanel({ childVersionId })` — `GET /v1/work-versions/{childVersionId}/diff`, the selected version vs. its own parent |
| `front/src/components/work/lineage-strip.tsx` | compact entry point on the work page |
| `back/app/domain/lineage/service.py` | `build_tree` / `ancestors` / `descendants` — the data source |
| `front/src/lib/api/types.ts` | `LineageNode` / `LineageResponse` |

## Invariants

1. **Layout is computed by dagre; rendering is hand-drawn SVG.** No graph-visualization library: nodes must consume the same theme tokens as the rest of the page (see `zaolang-theming`) — a canvas-based approach would follow neither theming nor keyboard access.
2. **Both directions render simultaneously**: ancestors on one side, descendants on the other. Two nodes are visually distinct, for two different reasons: `direction === 'root'` is the chain's origin — `buildGraph` assigns it to the oldest ancestor (`index === 0`), and only to the focused work when `ancestors.length === 0` — and carries the `--amber` "original" badge; the focused work is `current: true` (`direction` `descendant` whenever it has ancestors) and carries the `--primary` "current work" badge, with `accented = selected || node.current || node.direction === 'root'` driving the stroke. Don't read `root` as "the work you are looking at". Rendering only one direction degrades this into a "source list," not a graph.
3. **Tombstoned nodes must render as a placeholder, never disappear** (`tombstone: true` + `IconTombstone`), and must not be clickable into detail. A downstream work's provenance can't vanish — this is the frontend half of the backend's tombstone retention.
4. **Nodes are keyboard-reachable**: Tab traverses them, Enter/Space selects, the focus ring is visible. The graph is an interactive component, not an illustration.
5. **Depth is capped**: the backend's `build_tree` defaults to `max_depth=6`. Don't recursively expand further on the frontend — a long chain would blow up both the SVG and the response body.
6. **The parameter diff only compares the two sides of a single edge** — it shows the diff of `reusable_params_json`. The edge is chosen by selecting **one** node: `LineageExplorer` passes that node's `work_version_id` as `VersionDiffPanel`'s `childVersionId`, and the backend resolves the parent side (`GET /v1/work-versions/{id}/diff`); there is no two-node selection. A root version has no parent, so a failed/empty lookup there renders `diffEmpty`, not an error. Missing fields vs. changed values must be distinguishable (added / removed / modified, three distinct states).
7. **The graph is a read-only view**: remixing from here must still go through the normal `assert_remixable` authorization path — a node being visible doesn't imply it's remixable.

## Extension Points

- **Change the layout**: adjust dagre's `rankdir` / spacing constants and `NODE_WIDTH` / `NODE_HEIGHT`; after changing, verify no horizontal overflow at all three viewports (the visual suite checks this).
- **Add node info**: extend the backend `LineageNode` first (`app/domain/lineage/service.py`) → `make openapi` → frontend types follow automatically → node-size constants may need adjusting too.
- **Add a node state** (e.g. "under review"): add a new field alongside `direction` and `tombstone` — don't repurpose `tombstone` to mean something else.
- **Performance**: when node counts get large, truncate on the backend and show an "N more" hint rather than virtualizing on the frontend — this is a graph, not a list.

## Verify

```bash
make test-front
make test-a11y && make qa-visual
```

Manual path (`make seed` publishes no works — publish a work, remix it, and tombstone a second remix first, or use `tests/factories.make_work`): open the source work → the graph should show its remix and the tombstoned branch → click the remix's node → the panel below shows that version's parameter differences against its parent (`GET /v1/work-versions/{id}/diff`); clicking the origin node shows the empty-diff hint instead.
