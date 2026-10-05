import dagre from '@dagrejs/dagre';

import type { GraphNode } from './graph-model';

/** What `layoutGraph` needs: nodes (children keep their place) and the
 * top-level node-id pairs to rank by. */
export interface LayoutInput {
  nodes: GraphNode[];
  rankPairs: Array<[string, string]>;
}

const RANK_SEP = 96;
const NODE_SEP = 36;
const MARGIN = 24;

/**
 * Left-to-right dagre layout of the top-level look boxes (sources left of
 * what was derived from them), ranked by relation edges plus folded image
 * hints. Child image nodes keep their grid position inside their look
 * (`childPosition`). Deterministic: the same graph lays out the same way.
 *
 * `manual` holds positions the author dragged looks to this session; they
 * win over the computed ones until 整理布局 clears them.
 */
export function layoutGraph(
  built: LayoutInput,
  manual: Readonly<Record<string, { x: number; y: number }>> = {},
): GraphNode[] {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: 'LR',
    ranksep: RANK_SEP,
    nodesep: NODE_SEP,
    marginx: MARGIN,
    marginy: MARGIN,
  });
  graph.setDefaultEdgeLabel(() => ({}));
  const tops = built.nodes.filter((node) => !node.parentId);
  for (const node of tops) {
    graph.setNode(node.id, { width: node.width ?? 0, height: node.height ?? 0 });
  }
  for (const [from, to] of built.rankPairs) {
    if (from !== to && graph.hasNode(from) && graph.hasNode(to)) graph.setEdge(from, to);
  }
  dagre.layout(graph);
  return built.nodes.map((node) => {
    if (node.parentId) return node;
    const placed = graph.node(node.id);
    const computed = placed
      ? { x: placed.x - (node.width ?? 0) / 2, y: placed.y - (node.height ?? 0) / 2 }
      : node.position;
    return { ...node, position: manual[node.id] ?? computed } as GraphNode;
  });
}
