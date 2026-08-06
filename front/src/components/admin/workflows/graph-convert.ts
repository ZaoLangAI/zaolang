import type { Edge, Node } from '@xyflow/react';

import type { WorkflowEdgeData } from '@/components/admin/workflows/workflow-edge';
import type { WorkflowNodeData } from '@/components/admin/workflows/workflow-node';
import type { NodeTypeView, WorkflowGraphJson } from '@/lib/api/admin-types';

/** `WorkflowGraphJson` (the backend's `WorkflowGraph.to_dict()` shape) <->
 * `@xyflow/react`'s `Node`/`Edge` arrays. Kept in one place so the editor
 * component never hand-rolls either direction. */
export function graphToFlow(
  graph: WorkflowGraphJson,
  nodeTypesByType: Map<string, NodeTypeView>,
): { nodes: Node<WorkflowNodeData>[]; edges: Edge<WorkflowEdgeData>[] } {
  const nodes: Node<WorkflowNodeData>[] = graph.nodes.map((node, index) => {
    const spec = nodeTypesByType.get(node.type);
    return {
      id: node.id,
      type: 'workflowNode',
      position: node.position ?? { x: (index % 4) * 260, y: Math.floor(index / 4) * 180 },
      data: {
        nodeType: node.type,
        config: node.config ?? {},
        spec,
        label: spec?.label ?? node.type,
      },
    };
  });

  const edges: Edge<WorkflowEdgeData>[] = graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.from,
    sourceHandle: edge.from_port,
    target: edge.to,
    type: 'workflowEdge',
    data: { kind: edge.kind },
  }));

  return { nodes, edges };
}

export function flowToGraph(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge<WorkflowEdgeData>[],
): WorkflowGraphJson {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.data.nodeType,
      config: node.data.config,
      position: { x: node.position.x, y: node.position.y },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      from: edge.source,
      from_port: edge.sourceHandle ?? 'ok',
      to: edge.target,
      kind: edge.data?.kind ?? 'sequential',
    })),
  };
}
