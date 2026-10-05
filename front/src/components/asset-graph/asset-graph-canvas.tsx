'use client';

import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  type Connection,
  type EdgeChange,
  type EdgeTypes,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTranslations } from 'next-intl';
import { useMemo, useState, type CSSProperties } from 'react';

import { Button } from '@/components/ui/button';
import type { AssetGraph } from '@/lib/api/types';
import { useReducedMotion } from '@/lib/motion';

import {
  buildGraph,
  buildVoiceGraph,
  parseNodeId,
  type GraphNode,
  type GraphSelection,
  type RelationEdge,
} from './graph-model';
import { layoutGraph } from './layout';
import { EntryNodeCard } from './nodes/entry-node';
import { LookNodeCard } from './nodes/look-node';
import { PendingNodeCard } from './nodes/pending-node';
import { VoiceNodeCard } from './nodes/voice-node';
import { RelationEdgeLine } from './relation-edge';
import { RELATION_COLOR } from './relations';

/** Same bridge the studio canvas uses: React Flow's chrome follows our tokens. */
const CONTROLS_THEME_STYLE = {
  '--xy-controls-button-background-color': 'var(--surface)',
  '--xy-controls-button-background-color-hover': 'var(--surface-soft)',
  '--xy-controls-button-color': 'var(--text)',
  '--xy-controls-button-color-hover': 'var(--primary)',
  '--xy-controls-button-border-color': 'var(--border)',
} as CSSProperties;

const nodeTypes: NodeTypes = {
  look: LookNodeCard,
  entry: EntryNodeCard,
  pending: PendingNodeCard,
  voice: VoiceNodeCard,
};
const edgeTypes: EdgeTypes = { relation: RelationEdgeLine };

export interface AssetGraphCanvasProps {
  graph: AssetGraph;
  /** `looks`: looks and their images; `voices`: the character's voices. */
  mode: 'looks' | 'voices';
  expanded: ReadonlySet<string>;
  selection: GraphSelection;
  onSelect: (selection: GraphSelection) => void;
  onToggle: (variantId: string) => void;
  onToggleAll: (expand: boolean) => void;
  /** A drag between two handles of the same level. */
  onConnect: (level: 'variant' | 'entry' | 'voice', sourceId: string, targetId: string) => void;
  /** A drag between a look and an image (levels never mix). */
  onInvalidConnect: () => void;
}

/**
 * The management graph: React Flow over the dagre layout (`layout.ts`).
 * Selection is owned by the workspace (`selection`), so the inspector and
 * the outline view agree with the canvas; React Flow's own select events
 * (click, or Enter/Space on a focused node) only report into it. Looks can
 * be dragged for this session; 整理布局 restores the computed layout.
 */
export function AssetGraphCanvas(props: AssetGraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function CanvasInner({
  graph,
  mode,
  expanded,
  selection,
  onSelect,
  onToggle,
  onToggleAll,
  onConnect,
  onInvalidConnect,
}: AssetGraphCanvasProps) {
  const t = useTranslations('assetGraph');
  const reduced = useReducedMotion();
  const [manual, setManual] = useState<Record<string, { x: number; y: number }>>({});

  const built = useMemo(
    () =>
      mode === 'voices'
        ? buildVoiceGraph(graph, selection)
        : buildGraph(graph, { expanded, selection, onToggle }),
    [graph, mode, expanded, selection, onToggle],
  );
  const nodes = useMemo(() => layoutGraph(built, manual), [built, manual]);
  const edges = useMemo<RelationEdge[]>(
    () =>
      built.edges.map((edge) => ({
        ...edge,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
          color: edge.data?.hint
            ? 'var(--text-muted)'
            : RELATION_COLOR[edge.data?.relations[0] ?? 'custom'],
        },
      })),
    [built.edges],
  );

  const onNodesChange = (changes: NodeChange<GraphNode>[]) => {
    const moved: Record<string, { x: number; y: number }> = {};
    for (const change of changes) {
      if (change.type === 'position' && change.position) moved[change.id] = change.position;
      if (change.type === 'select' && change.selected) {
        const parsed = parseNodeId(change.id);
        if (parsed?.kind === 'variant') onSelect({ type: 'variant', id: parsed.id });
        if (parsed?.kind === 'entry') onSelect({ type: 'entry', id: parsed.id });
        if (parsed?.kind === 'voice') onSelect({ type: 'voice', id: parsed.id });
      }
    }
    if (Object.keys(moved).length) setManual((current) => ({ ...current, ...moved }));
  };

  const onEdgesChange = (changes: EdgeChange<RelationEdge>[]) => {
    for (const change of changes) {
      if (change.type === 'select' && change.selected && !change.id.startsWith('hint:')) {
        onSelect({ type: 'edge', id: change.id });
      }
    }
  };

  const connect = (connection: Connection) => {
    const source = parseNodeId(connection.source);
    const target = parseNodeId(connection.target);
    if (!source || !target || source.id === target.id) return;
    if (source.kind === 'variant' && target.kind === 'variant') {
      onConnect('variant', source.id, target.id);
    } else if (source.kind === 'entry' && target.kind === 'entry') {
      onConnect('entry', source.id, target.id);
    } else if (source.kind === 'voice' && target.kind === 'voice') {
      onConnect('voice', source.id, target.id);
    } else {
      onInvalidConnect();
    }
  };

  return (
    <ReactFlow<GraphNode, RelationEdge>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={connect}
      onPaneClick={() => onSelect({ type: 'card' })}
      isValidConnection={(connection) => {
        const source = parseNodeId(connection.source);
        const target = parseNodeId(connection.target);
        return Boolean(source && target && source.kind === target.kind && source.id !== target.id);
      }}
      deleteKeyCode={null}
      nodesFocusable
      edgesFocusable
      fitView
      fitViewOptions={{ padding: 0.2, maxZoom: 1, duration: reduced ? 0 : 200 }}
      minZoom={0.2}
      maxZoom={1.75}
      proOptions={{ hideAttribution: true }}
      style={CONTROLS_THEME_STYLE}
      ariaLabelConfig={{ 'node.a11yDescription.default': t('a11yNodeHint') }}
    >
      <Background gap={20} color="var(--border)" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        className="!bg-surface"
        nodeColor={(node) =>
          node.type === 'look' || node.type === 'voice' ? 'var(--border-strong)' : 'var(--border)'
        }
      />
      <Panel position="top-right" className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={() => setManual({})}>
          {t('relayout')}
        </Button>
        {mode === 'looks' ? (
          <>
            <Button size="sm" variant="secondary" onClick={() => onToggleAll(true)}>
              {t('expandAll')}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => onToggleAll(false)}>
              {t('collapseAll')}
            </Button>
          </>
        ) : null}
      </Panel>
    </ReactFlow>
  );
}
