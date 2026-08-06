'use client';

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  type EdgeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { NodeConfigForm, type NodeConfigSchema } from '@/components/admin/workflows/node-config-form';
import { flowToGraph, graphToFlow } from '@/components/admin/workflows/graph-convert';
import { WorkflowEdge, type WorkflowEdgeData } from '@/components/admin/workflows/workflow-edge';
import { WorkflowNode, type WorkflowNodeData } from '@/components/admin/workflows/workflow-node';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import type { NodeTypeView, WorkflowEdgeKind, WorkflowGraphJson } from '@/lib/api/admin-types';

const nodeTypes: NodeTypes = { workflowNode: WorkflowNode };
const edgeTypes: EdgeTypes = { workflowEdge: WorkflowEdge };
const EDGE_KINDS: WorkflowEdgeKind[] = ['sequential', 'parallel', 'retry'];

let localIdCounter = 0;
function nextNodeId(type: string): string {
  localIdCounter += 1;
  return `${type}_${Date.now().toString(36)}${localIdCounter}`;
}

/**
 * The actual `@xyflow/react` canvas: node palette, drag-to-add, connect,
 * per-node config panel, per-edge kind panel.
 *
 * Keyed by the caller on `(operation, templateId)` so switching operations
 * or reloading after a publish/rollback remounts this with a fresh initial
 * graph rather than trying to diff two unrelated graphs in place.
 */
export function WorkflowCanvas({
  initialGraph,
  nodeTypeCatalog,
  readOnly,
  onChange,
  onEditPrompt,
}: {
  initialGraph: WorkflowGraphJson;
  nodeTypeCatalog: NodeTypeView[];
  readOnly: boolean;
  onChange: (graph: WorkflowGraphJson) => void;
  onEditPrompt: (agentRole: string) => void;
}) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner
        initialGraph={initialGraph}
        nodeTypeCatalog={nodeTypeCatalog}
        readOnly={readOnly}
        onChange={onChange}
        onEditPrompt={onEditPrompt}
      />
    </ReactFlowProvider>
  );
}

function WorkflowCanvasInner({
  initialGraph,
  nodeTypeCatalog,
  readOnly,
  onChange,
  onEditPrompt,
}: {
  initialGraph: WorkflowGraphJson;
  nodeTypeCatalog: NodeTypeView[];
  readOnly: boolean;
  onChange: (graph: WorkflowGraphJson) => void;
  onEditPrompt: (agentRole: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const nodeTypesByType = useMemo(
    () => new Map(nodeTypeCatalog.map((spec) => [spec.type, spec])),
    [nodeTypeCatalog],
  );
  const initial = useMemo(
    () => graphToFlow(initialGraph, nodeTypesByType),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<WorkflowNodeData>>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<WorkflowEdgeData>>(initial.edges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  useEffect(() => {
    onChange(flowToGraph(nodes, edges));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) =>
        addEdge<Edge<WorkflowEdgeData>>(
          { ...connection, type: 'workflowEdge', data: { kind: 'sequential' } },
          current,
        ),
      );
    },
    [setEdges],
  );

  const addNode = useCallback(
    (spec: NodeTypeView, position: { x: number; y: number }) => {
      const id = nextNodeId(spec.type);
      setNodes((current) => [
        ...current,
        {
          id,
          type: 'workflowNode',
          position,
          data: { nodeType: spec.type, config: {}, spec, label: spec.label },
        },
      ]);
    },
    [setNodes],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData('application/x-workflow-node-type');
      const spec = nodeTypesByType.get(type);
      if (!spec) return;
      addNode(spec, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
    },
    [addNode, nodeTypesByType, screenToFlowPosition],
  );

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) ?? null;

  const updateNodeConfig = (config: Record<string, unknown>) => {
    if (!selectedNode) return;
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedNode.id ? { ...node, data: { ...node.data, config } } : node,
      ),
    );
  };

  const updateEdgeKind = (kind: WorkflowEdgeKind) => {
    if (!selectedEdge) return;
    setEdges((current) =>
      current.map((edge) =>
        edge.id === selectedEdge.id ? { ...edge, data: { ...edge.data, kind } } : edge,
      ),
    );
  };

  const deleteSelected = () => {
    if (selectedNodeId) {
      setNodes((current) => current.filter((node) => node.id !== selectedNodeId));
      setEdges((current) =>
        current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId),
      );
      setSelectedNodeId(null);
    }
    if (selectedEdgeId) {
      setEdges((current) => current.filter((edge) => edge.id !== selectedEdgeId));
      setSelectedEdgeId(null);
    }
  };

  return (
    <div className="flex h-[70vh] min-h-[520px] gap-3">
      {!readOnly ? (
        <aside className="w-48 shrink-0 overflow-y-auto rounded-[var(--radius-md)] border border-border bg-surface p-3">
          <p className="mb-2 text-xs font-semibold text-muted">{t('palette')}</p>
          <div className="flex flex-col gap-1.5">
            {nodeTypeCatalog.map((spec) => (
              <button
                key={spec.type}
                type="button"
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData('application/x-workflow-node-type', spec.type);
                  event.dataTransfer.effectAllowed = 'move';
                }}
                onClick={() => addNode(spec, { x: 40 + Math.random() * 40, y: 40 + Math.random() * 200 })}
                className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 py-2 text-left text-xs transition-colors hover:border-primary/50 hover:bg-primary/8"
                title={spec.description}
              >
                <span className="block font-medium">{spec.label}</span>
                <span className="block truncate font-mono text-[10px] text-muted">{spec.type}</span>
              </button>
            ))}
          </div>
        </aside>
      ) : null}

      <div
        ref={wrapperRef}
        className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-border"
        onDrop={readOnly ? undefined : onDrop}
        onDragOver={readOnly ? undefined : (event) => event.preventDefault()}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={readOnly ? undefined : onNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          onConnect={readOnly ? undefined : onConnect}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          elementsSelectable
          deleteKeyCode={readOnly ? [] : ['Backspace', 'Delete']}
          onNodeClick={(_, node) => {
            setSelectedNodeId(node.id);
            setSelectedEdgeId(null);
          }}
          onEdgeClick={(_, edge) => {
            setSelectedEdgeId(edge.id);
            setSelectedNodeId(null);
          }}
          onPaneClick={() => {
            setSelectedNodeId(null);
            setSelectedEdgeId(null);
          }}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!bg-surface" />
        </ReactFlow>
      </div>

      <aside className="w-72 shrink-0 overflow-y-auto rounded-[var(--radius-md)] border border-border bg-surface p-3">
        {selectedNode ? (
          <div className="flex flex-col gap-3">
            <div>
              <p className="text-sm font-semibold">{selectedNode.data.label}</p>
              <p className="font-mono text-[11px] text-muted">{selectedNode.data.nodeType}</p>
              {selectedNode.data.spec ? (
                <p className="mt-1 text-xs text-muted">{selectedNode.data.spec.description}</p>
              ) : (
                <Badge tone="danger" className="mt-1">
                  {t('unknownNodeType')}
                </Badge>
              )}
            </div>

            {selectedNode.data.spec?.is_agent && selectedNode.data.spec.agent_role ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onEditPrompt(selectedNode.data.spec!.agent_role!)}
              >
                {t('editPrompt')}
              </Button>
            ) : null}

            {selectedNode.data.spec ? (
              <div className="border-t border-border pt-3">
                <p className="mb-2 text-xs font-semibold text-muted">{t('nodeConfig')}</p>
                <NodeConfigForm
                  schema={selectedNode.data.spec.config_schema as unknown as NodeConfigSchema}
                  value={selectedNode.data.config}
                  disabled={readOnly}
                  onChange={updateNodeConfig}
                />
              </div>
            ) : null}

            {!readOnly ? (
              <Button variant="danger" size="sm" onClick={deleteSelected} className="mt-2">
                {t('deleteNode')}
              </Button>
            ) : null}
          </div>
        ) : selectedEdge ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm font-semibold">{t('edgeProperties')}</p>
            <p className="text-xs text-muted">
              {selectedEdge.source} <span className="font-mono">:{selectedEdge.sourceHandle}</span> →{' '}
              {selectedEdge.target}
            </p>
            <Select
              label={t('edgeKind')}
              disabled={readOnly}
              value={selectedEdge.data?.kind ?? 'sequential'}
              onChange={(event) => updateEdgeKind(event.target.value as WorkflowEdgeKind)}
              options={EDGE_KINDS.map((kind) => ({ value: kind, label: t(`edgeKind_${kind}`) }))}
            />
            {!readOnly ? (
              <Button variant="danger" size="sm" onClick={deleteSelected}>
                {t('deleteEdge')}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-muted">{t('selectHint')}</p>
        )}
      </aside>
    </div>
  );
}
