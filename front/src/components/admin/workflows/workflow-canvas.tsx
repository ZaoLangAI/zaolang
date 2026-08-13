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
  type IsValidConnection,
  type Node,
  type NodeTypes,
  type EdgeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Link } from '@/i18n/navigation';
import {
  describeAgent,
  useAgentCatalog,
  type AgentCatalog,
} from '@/components/admin/workflows/agent-catalog';
import { flowToGraph, graphToFlow } from '@/components/admin/workflows/graph-convert';
import {
  useGraphHistory,
  type GraphSnapshot,
} from '@/components/admin/workflows/use-graph-history';
import { NodeConfigForm } from '@/components/admin/workflows/node-config-form';
import { WorkflowEdge, type WorkflowEdgeData } from '@/components/admin/workflows/workflow-edge';
import { WorkflowNode, type WorkflowNodeData } from '@/components/admin/workflows/workflow-node';
import {
  WorkflowAnchorEdge,
  WorkflowAnchorNode,
} from '@/components/admin/workflows/workflow-anchor-node';
import {
  ANCHOR_EDGE_TYPE,
  ANCHOR_NODE_TYPE,
  computeAnchors,
} from '@/components/admin/workflows/workflow-anchors';
import { Button } from '@/components/ui/button';
import { Select, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import type { PromptEditTarget } from '@/components/admin/workflows/workflow-editor';
import type {
  NodeTypeView,
  WorkflowEdgeKind,
  WorkflowGraphJson,
} from '@/lib/api/admin-types';

const nodeTypes: NodeTypes = { workflowNode: WorkflowNode, [ANCHOR_NODE_TYPE]: WorkflowAnchorNode };
const edgeTypes: EdgeTypes = { workflowEdge: WorkflowEdge, [ANCHOR_EDGE_TYPE]: WorkflowAnchorEdge };
const EDGE_KINDS: WorkflowEdgeKind[] = ['sequential', 'parallel', 'retry'];

// The order the palette groups categories in — a fixed, product-decided
// reading order (moderation first because it can veto everything after it,
// terminal last because nothing follows it), not alphabetical.
const CATEGORY_ORDER = [
  'moderation',
  'context',
  'planning',
  'routing',
  'generation',
  'quality',
  'control',
  'terminal',
] as const;

let localIdCounter = 0;
function nextNodeId(type: string): string {
  localIdCounter += 1;
  return `${type}_${Date.now().toString(36)}${localIdCounter}`;
}

/** Falls back to the backend's Chinese string when a message key is missing
 * — e.g. a node type shipped before the console messages caught up. */
function tOr(t: ReturnType<typeof useTranslations>, key: string, fallback: string): string {
  try {
    const value = t(key);
    return value === key ? fallback : value;
  } catch {
    return fallback;
  }
}

/**
 * One human-readable line about what a node is wired to.
 *
 * Agent-bound nodes describe the agent (name · model, or the role default);
 * everything else falls back to a couple of its own non-empty config values,
 * same as the summary this replaced. Never the raw `ap_…` id — that only
 * ever appears in a tooltip (admin-console invariant #10).
 */
function summarizeNode(
  spec: NodeTypeView | undefined,
  config: Record<string, unknown>,
  catalog: AgentCatalog,
  t: ReturnType<typeof useTranslations>,
): string {
  if (!spec) return '';
  const str = (value: unknown) => (typeof value === 'string' && value.trim() ? value : '');

  const dynamic = spec.dynamic_agent_binding;
  if (dynamic) {
    const role = str(config[dynamic.role_field]);
    if (!role) return '';
    const roleLabel = catalog.nodes.find((node) => node.role === role)?.display_name ?? role;
    const agentId = str(config[dynamic.config_field]);
    const agent = agentId ? catalog.profileById(agentId) : catalog.defaultProfileOf(role);
    const agentLabel = agent
      ? describeAgent(agent)
      : agentId
        ? t('agentMissingOption', { id: agentId })
        : t('agentDefaultOptionPlain');
    return `${roleLabel} → ${agentLabel}`;
  }

  for (const binding of spec.agent_bindings ?? []) {
    const agentId = str(config[binding.config_field]);
    const agent = agentId ? catalog.profileById(agentId) : catalog.defaultProfileOf(binding.role);
    if (agent) return describeAgent(agent);
    if (agentId) return t('agentMissingOption', { id: agentId });
  }

  const entries = Object.entries(config).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  );
  if (entries.length === 0) return '';
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('/') : String(value)}`)
    .join('  ');
}

/** Every output port reachable on the branches feeding `nodeId`, for the
 * `join` node's success-port checklist — the union of `output_ports` across
 * every node with a path into it. */
function upstreamPorts(
  nodeId: string,
  edges: Edge<WorkflowEdgeData>[],
  nodesByType: Map<string, NodeTypeView>,
  nodeTypeById: Map<string, string>,
): string[] {
  const incoming = edges.filter((edge) => edge.target === nodeId);
  const ports = new Set<string>();
  for (const edge of incoming) {
    const spec = nodesByType.get(nodeTypeById.get(edge.source) ?? '');
    for (const port of spec?.output_ports ?? []) ports.add(port);
  }
  return [...ports];
}

export interface WorkflowCanvasProps {
  initialGraph: WorkflowGraphJson;
  nodeTypeCatalog: NodeTypeView[];
  readOnly: boolean;
  /** Node id → the publish-validation messages naming it, so a graph that
   * would fail to publish is outlined right where the problem is. */
  invalidNodeErrors?: Map<string, string[]>;
  /** Node id → how many `workflow_engine_failure` `SystemLog` rows named it
   * in the last 7 days — structurally valid, but has actually blown up. */
  hotspotCounts?: Map<string, number>;
  /** Walked node ids from a live sandbox run, for highlighting the path. */
  trace?: Array<{ node_id: string; port?: string | null }> | null;
  onChange: (graph: WorkflowGraphJson) => void;
  /** Fired once per *committed* edit — never on a drag's intermediate
   * frames or on the initial mount sync — so the editor can show an
   * "unpublished changes" badge and guard navigation. */
  onDirty?: () => void;
  onEditPrompt: (target: PromptEditTarget) => void;
}

/**
 * The actual `@xyflow/react` canvas: node palette, drag-to-add, connect,
 * per-node config panel, per-edge kind panel, undo/redo, copy/paste.
 *
 * Keyed by the caller on `(operation, templateId)` so switching operations
 * or reloading after a publish/rollback remounts this with a fresh initial
 * graph rather than trying to diff two unrelated graphs in place.
 */
export function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function WorkflowCanvasInner({
  initialGraph,
  nodeTypeCatalog,
  readOnly,
  invalidNodeErrors,
  hotspotCounts,
  trace,
  onChange,
  onDirty,
  onEditPrompt,
}: WorkflowCanvasProps) {
  const t = useTranslations('adminWorkflows');
  const catalog = useAgentCatalog();
  const nodeTypesByType = useMemo(
    () => new Map(nodeTypeCatalog.map((spec) => [spec.type, spec])),
    [nodeTypeCatalog],
  );
  const initial = useMemo(
    () => graphToFlow(initialGraph, nodeTypesByType),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [nodes, setNodes, onNodesChangeInternal] = useNodesState<Node<WorkflowNodeData>>(
    initial.nodes,
  );
  const [edges, setEdges, onEdgesChangeInternal] = useEdgesState<Edge<WorkflowEdgeData>>(
    initial.edges,
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [paletteQuery, setPaletteQuery] = useState('');
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();
  const history = useGraphHistory();

  // Fired once on mount so the parent's `workingGraph` starts out equal to
  // the graph actually on screen, even before any edit — the publish dialog
  // must be able to (re-)publish the unmodified graph.
  useEffect(() => {
    onChange(flowToGraph(initial.nodes, initial.edges));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Every structural or config mutation funnels through here: it pushes the
   * *pre*-mutation state onto the undo stack, applies the new state, and
   * reports the new graph up — the single place that keeps history, canvas
   * state and the parent's `workingGraph` from drifting apart.
   */
  const commit = useCallback(
    (nextNodes: Node<WorkflowNodeData>[], nextEdges: Edge<WorkflowEdgeData>[]) => {
      history.commit({ nodes, edges });
      setNodes(nextNodes);
      setEdges(nextEdges);
      onChange(flowToGraph(nextNodes, nextEdges));
      onDirty?.();
    },
    [nodes, edges, history, setNodes, setEdges, onChange, onDirty],
  );

  // Config-field edits (free text/number boxes) fire on every keystroke.
  // Reporting each one to the parent keeps validation/dirty state live, but
  // pushing every keystroke onto the undo stack would make reverting one
  // edit take dozens of Ctrl+Z presses — so only the *history* write is
  // coalesced: the first edit in a burst snapshots the pre-edit graph, later
  // edits within the same burst reuse it, and the snapshot lands on the
  // stack once the burst goes quiet.
  const burstSnapshotRef = useRef<GraphSnapshot | null>(null);
  const burstTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
    },
    [],
  );
  const commitDebounced = useCallback(
    (nextNodes: Node<WorkflowNodeData>[], nextEdges: Edge<WorkflowEdgeData>[]) => {
      if (!burstSnapshotRef.current) burstSnapshotRef.current = { nodes, edges };
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
      setNodes(nextNodes);
      setEdges(nextEdges);
      onChange(flowToGraph(nextNodes, nextEdges));
      onDirty?.();
      burstTimerRef.current = setTimeout(() => {
        if (burstSnapshotRef.current) {
          history.commit(burstSnapshotRef.current);
          burstSnapshotRef.current = null;
        }
      }, 700);
    },
    [nodes, edges, history, setNodes, setEdges, onChange, onDirty],
  );

  const undo = useCallback(() => {
    const previous = history.undo({ nodes, edges });
    if (!previous) return;
    setNodes(previous.nodes);
    setEdges(previous.edges);
    onChange(flowToGraph(previous.nodes, previous.edges));
    onDirty?.();
  }, [history, nodes, edges, setNodes, setEdges, onChange, onDirty]);

  const redo = useCallback(() => {
    const next = history.redo({ nodes, edges });
    if (!next) return;
    setNodes(next.nodes);
    setEdges(next.edges);
    onChange(flowToGraph(next.nodes, next.edges));
    onDirty?.();
  }, [history, nodes, edges, setNodes, setEdges, onChange, onDirty]);

  // Only a drag's *end* is a committed change — every frame in between is
  // `onNodesChangeInternal` moving the node, which must stay cheap.
  const dragSnapshotRef = useRef<GraphSnapshot | null>(null);
  const onNodeDragStart = useCallback(() => {
    dragSnapshotRef.current = { nodes, edges };
  }, [nodes, edges]);
  const onNodeDragStop = useCallback(() => {
    if (dragSnapshotRef.current) {
      history.commit(dragSnapshotRef.current);
      dragSnapshotRef.current = null;
    }
    onChange(flowToGraph(nodes, edges));
    onDirty?.();
  }, [nodes, edges, history, onChange, onDirty]);

  const isValidConnection = useCallback<IsValidConnection<Edge<WorkflowEdgeData>>>(
    (connection) => {
      const { source, target } = connection;
      const sourceHandle = connection.sourceHandle ?? null;
      if (!source || !target || source === target) return false;
      const duplicate = edges.some(
        (edge) =>
          edge.source === source &&
          edge.target === target &&
          (edge.sourceHandle ?? null) === sourceHandle,
      );
      if (duplicate) return false;
      // A new connection is always created as `sequential` (see `onConnect`),
      // so it conflicts with any existing non-`parallel` edge off the same
      // port — `_walk` only ever follows one of them (`graph.py::_port_errors`).
      const portTaken = edges.some(
        (edge) =>
          edge.source === source &&
          (edge.sourceHandle ?? null) === sourceHandle &&
          (edge.data?.kind ?? 'sequential') !== 'parallel',
      );
      return !portTaken;
    },
    [edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const nextEdges = addEdge<Edge<WorkflowEdgeData>>(
        { ...connection, type: 'workflowEdge', data: { kind: 'sequential' } },
        edges,
      );
      commit(nodes, nextEdges);
    },
    [nodes, edges, commit],
  );

  const addNode = useCallback(
    (spec: NodeTypeView, position: { x: number; y: number }) => {
      const id = nextNodeId(spec.type);
      commit(
        [
          ...nodes,
          {
            id,
            type: 'workflowNode',
            position,
            data: { nodeType: spec.type, config: {}, spec, label: spec.label, title: '' },
          },
        ],
        edges,
      );
    },
    [nodes, edges, commit],
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

  const deleteByIds = useCallback(
    (nodeIds: string[], edgeIds: string[]) => {
      if (nodeIds.length === 0 && edgeIds.length === 0) return;
      const nextNodes = nodes.filter((node) => !nodeIds.includes(node.id));
      const nextEdges = edges.filter(
        (edge) =>
          !edgeIds.includes(edge.id) &&
          !nodeIds.includes(edge.source) &&
          !nodeIds.includes(edge.target),
      );
      commit(nextNodes, nextEdges);
      if (selectedNodeId && nodeIds.includes(selectedNodeId)) setSelectedNodeId(null);
      if (selectedEdgeId && edgeIds.includes(selectedEdgeId)) setSelectedEdgeId(null);
    },
    [nodes, edges, commit, selectedNodeId, selectedEdgeId],
  );

  const deleteSelected = useCallback(() => {
    deleteByIds(selectedNodeId ? [selectedNodeId] : [], selectedEdgeId ? [selectedEdgeId] : []);
  }, [deleteByIds, selectedNodeId, selectedEdgeId]);

  // Ctrl/Cmd+C copies every currently-selected node (box-select or
  // shift-click); Ctrl/Cmd+V drops them back in with new ids, an offset
  // position and a deep-cloned config, so pasting twice never aliases the
  // same config object between two nodes.
  const clipboardRef = useRef<Node<WorkflowNodeData>[]>([]);
  const copySelected = useCallback(() => {
    const selected = nodes.filter((node) => node.selected);
    if (selected.length > 0) clipboardRef.current = selected;
  }, [nodes]);
  const pasteClipboard = useCallback(() => {
    if (clipboardRef.current.length === 0) return;
    const pasted = clipboardRef.current.map((node) => ({
      ...node,
      id: nextNodeId(node.data.nodeType),
      position: { x: node.position.x + 48, y: node.position.y + 48 },
      selected: true,
      data: { ...node.data, config: structuredClone(node.data.config) },
    }));
    commit([...nodes.map((node) => ({ ...node, selected: false })), ...pasted], edges);
  }, [nodes, edges, commit]);

  useEffect(() => {
    if (readOnly) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isEditable =
        !!target &&
        (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable);
      if (isEditable) return;
      const meta = event.metaKey || event.ctrlKey;
      if (!meta) return;
      const key = event.key.toLowerCase();
      if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (key === 'c') {
        copySelected();
      } else if (key === 'v') {
        event.preventDefault();
        pasteClipboard();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [readOnly, undo, redo, copySelected, pasteClipboard]);

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) ?? null;

  const updateNodeConfig = (config: Record<string, unknown>) => {
    if (!selectedNode) return;
    commitDebounced(
      nodes.map((node) =>
        node.id === selectedNode.id ? { ...node, data: { ...node.data, config } } : node,
      ),
      edges,
    );
  };

  const updateNodeTitle = (title: string) => {
    if (!selectedNode) return;
    commitDebounced(
      nodes.map((node) =>
        node.id === selectedNode.id ? { ...node, data: { ...node.data, title } } : node,
      ),
      edges,
    );
  };

  const updateEdgeKind = (kind: WorkflowEdgeKind) => {
    if (!selectedEdge) return;
    commit(
      nodes,
      edges.map((edge) =>
        edge.id === selectedEdge.id ? { ...edge, data: { ...edge.data, kind } } : edge,
      ),
    );
  };

  const nodeTypeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node.data.nodeType])),
    [nodes],
  );
  const availablePorts = selectedNode
    ? upstreamPorts(selectedNode.id, edges, nodeTypesByType, nodeTypeById)
    : [];

  const tracedPortByNode = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const step of trace ?? []) map.set(step.node_id, step.port ?? null);
    return map;
  }, [trace]);
  const tracedEdgeIds = useMemo(() => {
    const ids = new Set<string>();
    const steps = trace ?? [];
    for (let index = 0; index < steps.length - 1; index += 1) {
      const from = steps[index]!;
      const to = steps[index + 1]!;
      for (const edge of edges) {
        if (edge.source === from.node_id && edge.target === to.node_id) {
          if (from.port && (edge.sourceHandle ?? 'ok') !== from.port) continue;
          ids.add(edge.id);
        }
      }
    }
    return ids;
  }, [trace, edges]);

  const displayNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          summary: summarizeNode(node.data.spec, node.data.config, catalog, t),
          broken: (invalidNodeErrors?.get(node.id)?.length ?? 0) > 0,
          hotspot: (hotspotCounts?.get(node.id) ?? 0) > 0,
          tracedPort: tracedPortByNode.get(node.id) ?? null,
        },
      })),
    [nodes, catalog, t, invalidNodeErrors, hotspotCounts, tracedPortByNode],
  );

  const displayEdges = useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        data: { kind: edge.data?.kind ?? 'sequential', traced: tracedEdgeIds.has(edge.id) },
      })),
    [edges, tracedEdgeIds],
  );

  // Canvas-only "开始"/"结束" markers — derived from `nodes`/`edges`, never
  // part of `graph_json` or undo history. See `computeAnchors`.
  const anchors = useMemo(
    () => computeAnchors(nodes, edges, { start: t('startNode'), end: t('endNode') }),
    [nodes, edges, t],
  );
  const canvasNodes = useMemo(
    () => [...displayNodes, ...anchors.nodes],
    [displayNodes, anchors.nodes],
  );
  const canvasEdges = useMemo(
    () => [...displayEdges, ...anchors.edges],
    [displayEdges, anchors.edges],
  );

  const categories = useMemo(() => {
    const query = paletteQuery.trim().toLowerCase();
    const matches = nodeTypeCatalog.filter((spec) => {
      if (!query) return true;
      const label = tOr(t, spec.label_key, spec.label).toLowerCase();
      return label.includes(query) || spec.type.toLowerCase().includes(query);
    });
    const byCategory = new Map<string, NodeTypeView[]>();
    for (const spec of matches) {
      const list = byCategory.get(spec.category) ?? [];
      list.push(spec);
      byCategory.set(spec.category, list);
    }
    const order = [
      ...CATEGORY_ORDER.filter((category) => byCategory.has(category)),
      ...[...byCategory.keys()]
        .filter((category) => !CATEGORY_ORDER.includes(category as never))
        .sort(),
    ];
    return order.map((category) => ({ category, specs: byCategory.get(category) ?? [] }));
  }, [nodeTypeCatalog, paletteQuery, t]);

  const selectedNodeErrors = selectedNode ? (invalidNodeErrors?.get(selectedNode.id) ?? []) : [];
  const selectedNodeHotspot = selectedNode ? (hotspotCounts?.get(selectedNode.id) ?? 0) : 0;

  return (
    <div className="flex flex-col gap-2">
      {!readOnly ? (
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" disabled={!history.canUndo} onClick={undo}>
            ↶ {t('undo')}
          </Button>
          <Button size="sm" variant="ghost" disabled={!history.canRedo} onClick={redo}>
            ↷ {t('redo')}
          </Button>
        </div>
      ) : null}

      <div className="flex h-[70vh] min-h-[520px] gap-3">
        {!readOnly ? (
          <aside className="w-52 shrink-0 overflow-y-auto rounded-[var(--radius-md)] border border-border bg-surface p-3">
            <p className="mb-2 text-xs font-semibold text-muted">{t('palette')}</p>
            <TextInput
              label={t('paletteSearch')}
              layout="stacked"
              className="h-9 text-xs"
              value={paletteQuery}
              onChange={(event) => setPaletteQuery(event.target.value)}
              placeholder={t('paletteSearch')}
            />
            {categories.every((group) => group.specs.length === 0) ? (
              <p className="mt-3 text-xs text-muted">{t('paletteEmpty')}</p>
            ) : (
              <div className="mt-3 flex flex-col gap-3">
                {categories.map((group) =>
                  group.specs.length === 0 ? null : (
                    <div key={group.category}>
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted/80">
                        {tOr(t, `nodeCategory_${group.category}`, group.category)}
                      </p>
                      <div className="flex flex-col gap-1.5">
                        {group.specs.map((spec) => (
                          <button
                            key={spec.type}
                            type="button"
                            draggable
                            onDragStart={(event) => {
                              event.dataTransfer.setData(
                                'application/x-workflow-node-type',
                                spec.type,
                              );
                              event.dataTransfer.effectAllowed = 'move';
                            }}
                            onClick={() =>
                              addNode(spec, {
                                x: 40 + Math.random() * 40,
                                y: 40 + Math.random() * 200,
                              })
                            }
                            className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 py-2 text-left text-xs transition-colors hover:border-primary/50 hover:bg-primary/8"
                            title={tOr(t, spec.description_key, spec.description)}
                          >
                            <span className="block font-medium">
                              {tOr(t, spec.label_key, spec.label)}
                            </span>
                            <span className="block truncate font-mono text-[10px] text-muted">
                              {spec.type}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ),
                )}
              </div>
            )}
          </aside>
        ) : null}

        <div
          ref={wrapperRef}
          className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-border"
          onDrop={readOnly ? undefined : onDrop}
          onDragOver={readOnly ? undefined : (event) => event.preventDefault()}
        >
          <ReactFlow
            nodes={canvasNodes}
            edges={canvasEdges}
            onNodesChange={readOnly ? undefined : onNodesChangeInternal}
            onEdgesChange={readOnly ? undefined : onEdgesChangeInternal}
            onNodeDragStart={readOnly ? undefined : onNodeDragStart}
            onNodeDragStop={readOnly ? undefined : onNodeDragStop}
            onConnect={readOnly ? undefined : onConnect}
            isValidConnection={readOnly ? undefined : isValidConnection}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            elementsSelectable
            // Delete is handled by our own keydown listener (`deleteByIds`),
            // which also drives undo history — the built-in handler would
            // remove nodes/edges without ever telling us it happened.
            deleteKeyCode={[]}
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
                <p className="text-sm font-semibold">
                  {selectedNode.data.title || selectedNode.data.label}
                </p>
                <p className="font-mono text-[11px] text-muted" title={selectedNode.id}>
                  {selectedNode.data.nodeType}
                </p>
                {selectedNode.data.spec ? (
                  <p className="mt-1 text-xs text-muted">
                    {tOr(
                      t,
                      selectedNode.data.spec.description_key,
                      selectedNode.data.spec.description,
                    )}
                  </p>
                ) : (
                  <Badge tone="danger" className="mt-1">
                    {t('unknownNodeType')}
                  </Badge>
                )}
              </div>

              <TextInput
                label={t('nodeTitle')}
                hint={t('nodeTitleHint')}
                disabled={readOnly}
                value={selectedNode.data.title ?? ''}
                maxLength={60}
                onChange={(event) => updateNodeTitle(event.target.value)}
              />

              {selectedNodeErrors.length > 0 ? (
                <div className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 p-2.5">
                  <p className="text-xs font-medium text-danger">{t('nodeProblems')}</p>
                  <ul className="mt-1 list-disc pl-4 text-[11px] text-muted">
                    {selectedNodeErrors.map((message, index) => (
                      <li key={index}>{message}</li>
                    ))}
                  </ul>
                </div>
              ) : selectedNodeHotspot > 0 ? (
                <div className="rounded-[var(--radius-sm)] border border-amber/40 bg-amber/8 p-2.5">
                  <p className="text-xs font-medium text-amber">
                    {t('engineFailureHotspot')} · {selectedNodeHotspot}
                  </p>
                  <p className="mt-1 text-[11px] text-muted">{t('engineFailureHotspotHint')}</p>
                  <Link
                    href="/admin/audit"
                    className="mt-1.5 inline-block text-[11px] text-primary underline"
                  >
                    {t('viewEngineFailures')}
                  </Link>
                </div>
              ) : null}

              {selectedNode.data.spec?.dynamic_agent_binding ? (
                <PromptButton
                  binding={{
                    role:
                      typeof selectedNode.data.config[
                        selectedNode.data.spec.dynamic_agent_binding.role_field
                      ] === 'string'
                        ? String(
                            selectedNode.data.config[
                              selectedNode.data.spec.dynamic_agent_binding.role_field
                            ],
                          )
                        : '',
                    agentId:
                      typeof selectedNode.data.config[
                        selectedNode.data.spec.dynamic_agent_binding.config_field
                      ] === 'string'
                        ? String(
                            selectedNode.data.config[
                              selectedNode.data.spec.dynamic_agent_binding.config_field
                            ],
                          )
                        : null,
                    slot:
                      typeof selectedNode.data.config[
                        selectedNode.data.spec.dynamic_agent_binding.slot_field
                      ] === 'string'
                        ? String(
                            selectedNode.data.config[
                              selectedNode.data.spec.dynamic_agent_binding.slot_field
                            ],
                          )
                        : null,
                  }}
                  catalog={catalog}
                  onEditPrompt={onEditPrompt}
                />
              ) : (
                (selectedNode.data.spec?.agent_bindings ?? []).map((binding) => (
                  <PromptButton
                    key={binding.config_field}
                    binding={{
                      role: binding.role,
                      agentId:
                        typeof selectedNode.data.config[binding.config_field] === 'string'
                          ? String(selectedNode.data.config[binding.config_field])
                          : null,
                      slot: binding.slot,
                    }}
                    catalog={catalog}
                    onEditPrompt={onEditPrompt}
                  />
                ))
              )}

              {selectedNode.data.spec ? (
                <div className="border-t border-border pt-3">
                  <p className="mb-2 text-xs font-semibold text-muted">{t('nodeConfig')}</p>
                  <NodeConfigForm
                    spec={selectedNode.data.spec}
                    value={selectedNode.data.config}
                    disabled={readOnly}
                    availablePorts={
                      selectedNode.data.nodeType === 'join' ? availablePorts : undefined
                    }
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
                {selectedEdge.source}{' '}
                <span className="font-mono">:{selectedEdge.sourceHandle}</span> →{' '}
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
    </div>
  );
}

/** One "编辑 Prompt" button, labelled with the role (and slot, when there is
 * more than one prompt for that role) rather than always the same generic
 * text — the point of the fix being that a multi-binding node's buttons no
 * longer look identical. */
function PromptButton({
  binding,
  catalog,
  onEditPrompt,
}: {
  binding: PromptEditTarget;
  catalog: AgentCatalog;
  onEditPrompt: (target: PromptEditTarget) => void;
}) {
  const t = useTranslations('adminWorkflows');
  if (!binding.role) return null;
  const roleLabel =
    catalog.nodes.find((node) => node.role === binding.role)?.display_name ?? binding.role;
  const slots = catalog.slotsOf(binding.role);
  const label =
    slots.length > 1 && binding.slot
      ? `${t('editPromptFor', { role: roleLabel })} · ${
          slots.find((candidate) => candidate.key === binding.slot)?.label ?? binding.slot
        }`
      : t('editPromptFor', { role: roleLabel });

  return (
    <Button variant="secondary" size="sm" onClick={() => onEditPrompt(binding)}>
      {label}
    </Button>
  );
}
