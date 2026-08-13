'use client';

import * as dagre from '@dagrejs/dagre';
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
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';

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
import { Dialog } from '@/components/ui/dialog';
import { Select, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
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

// A rough card footprint (the 256px node body plus its port column) used only
// to space `dagre`'s layout out — not pixel-exact, since the operator can
// still drag a node afterwards; it only has to be big enough that laid-out
// cards don't overlap.
const AUTO_LAYOUT_NODE_WIDTH = 320;
const AUTO_LAYOUT_NODE_HEIGHT = 130;

/**
 * Bridges `@xyflow/react`'s own theming variables to our semantic tokens.
 *
 * The library ships a light palette by default and only offers a dark one
 * through its `.dark` class (`colorMode` prop) — a separate, un-branded grey
 * scale. Setting these variables here instead makes the zoom controls follow
 * whichever tokens `[data-theme]` currently resolves to, the same as every
 * other themed surface in the console, with no theme-aware JS branch needed.
 */
const CONTROLS_THEME_STYLE = {
  '--xy-controls-button-background-color': 'var(--surface)',
  '--xy-controls-button-background-color-hover': 'var(--surface-soft)',
  '--xy-controls-button-color': 'var(--text)',
  '--xy-controls-button-color-hover': 'var(--primary)',
  '--xy-controls-button-border-color': 'var(--border)',
} as CSSProperties;

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
}

/**
 * The actual `@xyflow/react` canvas: node palette, drag-to-add, connect,
 * double-click-to-edit dialogs, undo/redo, copy/paste.
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
  // Which node/edge the operator double-clicked into — drives the edit
  // dialogs below. Independent of `@xyflow/react`'s own click/box-select
  // state (`node.selected`), which `copySelected` still reads directly.
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editingEdgeId, setEditingEdgeId] = useState<string | null>(null);
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

  /**
   * Runs `dagre` over the graph as it stands (real nodes/edges only — the
   * canvas-only start/end anchors are derived, never part of this state) and
   * writes the result back as ordinary node positions, through `commit` like
   * any other edit. That is what makes it undoable and what makes the new
   * positions reach `WorkflowNode.position` the next time the graph is
   * published — no separate persistence path needed.
   */
  const autoLayout = useCallback(() => {
    if (nodes.length === 0) return;
    const layoutGraph = new dagre.graphlib.Graph();
    layoutGraph.setGraph({ rankdir: 'LR', nodesep: 56, ranksep: 96, marginx: 24, marginy: 24 });
    layoutGraph.setDefaultEdgeLabel(() => ({}));
    for (const node of nodes) {
      layoutGraph.setNode(node.id, {
        width: AUTO_LAYOUT_NODE_WIDTH,
        height: AUTO_LAYOUT_NODE_HEIGHT,
      });
    }
    for (const edge of edges) {
      layoutGraph.setEdge(edge.source, edge.target);
    }
    dagre.layout(layoutGraph);
    const nextNodes = nodes.map((node) => {
      const positioned = layoutGraph.node(node.id);
      if (!positioned) return node;
      return {
        ...node,
        position: {
          x: positioned.x - AUTO_LAYOUT_NODE_WIDTH / 2,
          y: positioned.y - AUTO_LAYOUT_NODE_HEIGHT / 2,
        },
      };
    });
    commit(nextNodes, edges);
  }, [nodes, edges, commit]);

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
      if (editingNodeId && nodeIds.includes(editingNodeId)) setEditingNodeId(null);
      if (editingEdgeId && edgeIds.includes(editingEdgeId)) setEditingEdgeId(null);
    },
    [nodes, edges, commit, editingNodeId, editingEdgeId],
  );

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

  const editingNode = nodes.find((node) => node.id === editingNodeId) ?? null;
  const editingEdge = edges.find((edge) => edge.id === editingEdgeId) ?? null;

  const updateNodeConfig = (config: Record<string, unknown>) => {
    if (!editingNode) return;
    commitDebounced(
      nodes.map((node) =>
        node.id === editingNode.id ? { ...node, data: { ...node.data, config } } : node,
      ),
      edges,
    );
  };

  const updateNodeTitle = (title: string) => {
    if (!editingNode) return;
    commitDebounced(
      nodes.map((node) =>
        node.id === editingNode.id ? { ...node, data: { ...node.data, title } } : node,
      ),
      edges,
    );
  };

  const updateEdgeKind = (kind: WorkflowEdgeKind) => {
    if (!editingEdge) return;
    commit(
      nodes,
      edges.map((edge) =>
        edge.id === editingEdge.id ? { ...edge, data: { ...edge.data, kind } } : edge,
      ),
    );
  };

  const deleteEditingNode = () => {
    if (!editingNode) return;
    deleteByIds([editingNode.id], []);
  };

  const deleteEditingEdge = () => {
    if (!editingEdge) return;
    deleteByIds([], [editingEdge.id]);
  };

  const nodeTypeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node.data.nodeType])),
    [nodes],
  );
  const availablePorts = editingNode
    ? upstreamPorts(editingNode.id, edges, nodeTypesByType, nodeTypeById)
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

  const editingNodeErrors = editingNode ? (invalidNodeErrors?.get(editingNode.id) ?? []) : [];
  const editingNodeHotspot = editingNode ? (hotspotCounts?.get(editingNode.id) ?? 0) : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        {!readOnly ? (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" disabled={!history.canUndo} onClick={undo}>
              ↶ {t('undo')}
            </Button>
            <Button size="sm" variant="ghost" disabled={!history.canRedo} onClick={redo}>
              ↷ {t('redo')}
            </Button>
            <Button size="sm" variant="ghost" onClick={autoLayout}>
              {t('autoLayout')}
            </Button>
          </div>
        ) : (
          <div />
        )}
        <p className="text-xs text-muted">{t('doubleClickHint')}</p>
      </div>

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
            // Deletion only happens from the node/edge dialogs below
            // (`deleteEditingNode` / `deleteEditingEdge`) — deliberately no
            // Delete/Backspace shortcut, so a stray keypress while typing in
            // a config field can never remove the node out from under it.
            deleteKeyCode={[]}
            onNodeDoubleClick={(_, node) => setEditingNodeId(node.id)}
            onEdgeDoubleClick={(_, edge) => setEditingEdgeId(edge.id)}
            fitView
            proOptions={{ hideAttribution: true }}
            style={CONTROLS_THEME_STYLE}
          >
            <Background />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-surface" />
          </ReactFlow>
        </div>
      </div>

      <Dialog
        open={editingNode !== null}
        onClose={() => setEditingNodeId(null)}
        title={editingNode?.data.label ?? t('nodeConfig')}
        size="lg"
        footer={
          <>
            {!readOnly ? (
              <Button variant="danger" onClick={deleteEditingNode}>
                {t('deleteNode')}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setEditingNodeId(null)}>
              {t('close')}
            </Button>
          </>
        }
      >
        {editingNode ? (
          <div className="flex flex-col gap-3">
            <div>
              <p className="font-mono text-[11px] text-muted" title={editingNode.id}>
                {editingNode.data.nodeType}
              </p>
              {!editingNode.data.spec ? (
                <Badge tone="danger" className="mt-1">
                  {t('unknownNodeType')}
                </Badge>
              ) : null}
            </div>

            <TextInput
              label={t('nodeTitle')}
              disabled={readOnly}
              value={editingNode.data.title ?? ''}
              maxLength={60}
              onChange={(event) => updateNodeTitle(event.target.value)}
            />

            {editingNodeErrors.length > 0 ? (
              <div className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 p-2.5">
                <p className="text-xs font-medium text-danger">{t('nodeProblems')}</p>
                <ul className="mt-1 list-disc pl-4 text-[11px] text-muted">
                  {editingNodeErrors.map((message, index) => (
                    <li key={index}>{message}</li>
                  ))}
                </ul>
              </div>
            ) : editingNodeHotspot > 0 ? (
              <div className="rounded-[var(--radius-sm)] border border-amber/40 bg-amber/8 p-2.5">
                <p className="text-xs font-medium text-amber">
                  {t('engineFailureHotspot')} · {editingNodeHotspot}
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

            {editingNode.data.spec ? (
              <div className="border-t border-border pt-3">
                <p className="mb-2 text-xs font-semibold text-muted">{t('nodeConfig')}</p>
                <NodeConfigForm
                  spec={editingNode.data.spec}
                  value={editingNode.data.config}
                  disabled={readOnly}
                  availablePorts={
                    editingNode.data.nodeType === 'join' ? availablePorts : undefined
                  }
                  onChange={updateNodeConfig}
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={editingEdge !== null}
        onClose={() => setEditingEdgeId(null)}
        title={t('edgeProperties')}
        description={
          editingEdge
            ? `${editingEdge.source} :${editingEdge.sourceHandle} → ${editingEdge.target}`
            : undefined
        }
        footer={
          <>
            {!readOnly ? (
              <Button variant="danger" onClick={deleteEditingEdge}>
                {t('deleteEdge')}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setEditingEdgeId(null)}>
              {t('close')}
            </Button>
          </>
        }
      >
        {editingEdge ? (
          <Select
            label={t('edgeKind')}
            disabled={readOnly}
            value={editingEdge.data?.kind ?? 'sequential'}
            onChange={(event) => updateEdgeKind(event.target.value as WorkflowEdgeKind)}
            options={EDGE_KINDS.map((kind) => ({ value: kind, label: t(`edgeKind_${kind}`) }))}
          />
        ) : null}
      </Dialog>
    </div>
  );
}
