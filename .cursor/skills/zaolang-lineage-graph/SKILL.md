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
| `front/src/components/lineage/lineage-graph.tsx` | dagre layout + hand-drawn SVG; `NODE_WIDTH/HEIGHT`, `GraphNode.direction` (`ancestor` / `root` / `descendant`) |
| `front/src/components/lineage/lineage-dialog.tsx` | full-screen viewer container |
| `front/src/components/lineage/version-diff-panel.tsx` | parent/child version parameter diff |
| `front/src/components/work/lineage-strip.tsx` | compact entry point on the work page |
| `back/app/domain/lineage/service.py` | `build_tree` / `ancestors` / `descendants` — the data source |
| `front/src/lib/api/types.ts` | `LineageNode` / `LineageResponse` |

## Invariants

1. **Layout is computed by dagre; rendering is hand-drawn SVG.** No graph-visualization library: nodes must consume the same theme tokens as the rest of the page (see `zaolang-theming`) — a canvas-based approach would follow neither theming nor keyboard access.
2. **Both directions render simultaneously**: ancestors on one side, descendants on the other, with the current work visually distinct as `root`. Rendering only one direction degrades this into a "source list," not a graph.
3. **Tombstoned nodes must render as a placeholder, never disappear** (`tombstone: true` + `IconTombstone`), and must not be clickable into detail. A downstream work's provenance can't vanish — this is the frontend half of the backend's tombstone retention.
4. **Nodes are keyboard-reachable**: Tab traverses them, Enter/Space selects, the focus ring is visible. The graph is an interactive component, not an illustration.
5. **Depth is capped**: the backend's `build_tree` defaults to `max_depth=6`. Don't recursively expand further on the frontend — a long chain would blow up both the SVG and the response body.
6. **The parameter diff only compares the two sides of a single edge** — it shows the diff of `reusable_params_json`. Missing fields vs. changed values must be distinguishable (added / removed / modified, three distinct states).
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

Manual path: open the seed work "Tide Above" → the graph should show its remix "Tide Above · Night Walk" and the tombstoned branch → click two adjacent versions → the diff panel shows the parameter differences.
