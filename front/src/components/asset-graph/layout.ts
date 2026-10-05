import dagre from '@dagrejs/dagre';

import type { BuiltGraph, GraphNode } from './graph-model';
import { variantNodeId } from './graph-model';

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
  built: BuiltGraph,
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
  for (const [source, target] of built.rankPairs) {
    const from = variantNodeId(source);
    const to = variantNodeId(target);
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
