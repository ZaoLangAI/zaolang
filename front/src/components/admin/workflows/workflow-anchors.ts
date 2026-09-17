import type { Edge, Node } from '@xyflow/react';

import type { WorkflowEdgeData } from '@/components/admin/workflows/workflow-edge';
import type { WorkflowNodeData } from '@/components/admin/workflows/workflow-node';

/** The two node *types* the backend treats as terminal (`graph.py`'s
 * `TERMINAL_NODE_TYPES`) — the only types allowed to settle credits or
 * release a reservation and move the job to a terminal `JobStatus`. */
const TERMINAL_NODE_TYPES = new Set(['settle_success', 'fail']);

export const START_ANCHOR_ID = '__start__';
export const END_ANCHOR_ID = '__end__';
export const ANCHOR_NODE_TYPE = 'workflowAnchor';
export const ANCHOR_EDGE_TYPE = 'workflowAnchorEdge';

/** Kept inside `WorkflowNodeData`'s own index signature rather than a
 * separate data type — that's what lets an anchor sit in the same
 * `Node<WorkflowNodeData>[]` array as real nodes without widening every
 * prop on `<ReactFlow>` (`onNodesChange`, `nodeTypes`, …) into a union. */
const ANCHOR_KIND_FIELD = 'anchorKind';

/**
 * Derives the canvas-only "开始"/"结束" marker nodes and their connecting
 * edges from the real graph — never persisted, never touched by undo/redo or
 * `flowToGraph`. Entry/terminal detection mirrors the backend's own rules
 * (`graph.py::validate`'s zero-incoming-edge entry check and
 * `TERMINAL_NODE_TYPES`) so what the canvas shows never disagrees with what
 * publish-time validation actually enforces.
 *
 * Tolerates the transient, possibly-invalid states an in-progress edit can
 * be in (zero or several entry/terminal nodes) instead of assuming the
 * exactly-one invariant already holds.
 */
export function computeAnchors(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge<WorkflowEdgeData>[],
  labels: { start: string; end: string },
): { nodes: Node<WorkflowNodeData>[]; edges: Edge<WorkflowEdgeData>[] } {
  if (nodes.length === 0) return { nodes: [], edges: [] };

  const hasIncoming = new Set(edges.map((edge) => edge.target));
  const entryNodes = nodes.filter((node) => !hasIncoming.has(node.id));
  const terminalNodes = nodes.filter((node) => TERMINAL_NODE_TYPES.has(node.data.nodeType));

  const anchorNodes: Node<WorkflowNodeData>[] = [];
  const anchorEdges: Edge<WorkflowEdgeData>[] = [];

  const shared = {
    selectable: false,
    draggable: false,
    connectable: false,
    deletable: false,
    focusable: false,
  } as const;

  if (entryNodes.length > 0) {
    const minX = Math.min(...entryNodes.map((node) => node.position.x));
    const avgY =
      entryNodes.reduce((sum, node) => sum + node.position.y, 0) / entryNodes.length;
    anchorNodes.push({
      id: START_ANCHOR_ID,
      type: ANCHOR_NODE_TYPE,
      position: { x: minX - 200, y: avgY + 16 },
      data: { nodeType: '', config: {}, spec: undefined, label: labels.start, [ANCHOR_KIND_FIELD]: 'start' },
      ...shared,
    });
    for (const node of entryNodes) {
      anchorEdges.push({
        id: `${START_ANCHOR_ID}->${node.id}`,
        source: START_ANCHOR_ID,
        target: node.id,
        type: ANCHOR_EDGE_TYPE,
        data: { kind: 'sequential' },
        ...shared,
      });
    }
  }

  if (terminalNodes.length > 0) {
    const maxX = Math.max(...terminalNodes.map((node) => node.position.x));
    const avgY =
      terminalNodes.reduce((sum, node) => sum + node.position.y, 0) / terminalNodes.length;
    anchorNodes.push({
      id: END_ANCHOR_ID,
      type: ANCHOR_NODE_TYPE,
      position: { x: maxX + 300, y: avgY + 16 },
      data: { nodeType: '', config: {}, spec: undefined, label: labels.end, [ANCHOR_KIND_FIELD]: 'end' },
      ...shared,
    });
    for (const node of terminalNodes) {
      anchorEdges.push({
        id: `${node.id}->${END_ANCHOR_ID}`,
        source: node.id,
        target: END_ANCHOR_ID,
        type: ANCHOR_EDGE_TYPE,
        data: { kind: 'sequential' },
        ...shared,
      });
    }
  }

  return { nodes: anchorNodes, edges: anchorEdges };
}

/** Reads the `anchorKind` an anchor node was built with — `undefined` for
 * every real node, since only `computeAnchors` ever sets this field. */
export function anchorKindOf(data: WorkflowNodeData): 'start' | 'end' | undefined {
  const value = data[ANCHOR_KIND_FIELD];
  return value === 'start' || value === 'end' ? value : undefined;
}
