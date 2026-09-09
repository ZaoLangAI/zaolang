'use client';

import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';

import { uploadFile } from '@/lib/upload';

import { CanvasContextMenu, type ContextMenuState } from './canvas-context-menu';
import { hasCanvasDrag, readCanvasDrag } from './canvas-dnd';
import { offsetGraph, parseCanvasFile, serializeCanvas } from './canvas-io';
import { CanvasNodeCard } from './canvas-node';
import { CanvasProperties } from './canvas-properties';
import { CanvasToolbar } from './canvas-toolbar';
import { DirectorDialog } from './director-dialog';
import { PromptLibraryPanel } from './prompt-library-panel';
import { useCanvasEditing } from './use-canvas-editing';
import {
  flowToGraph,
  graphToFlow,
  newCanvasEdgeId,
  newCanvasNodeId,
  upstreamAssetIds,
  type CanvasFlowEdge,
  type CanvasFlowNode,
} from './graph-convert';
import type { CanvasGraph, CanvasNodeBinding, CanvasNodeKind, CanvasSnapshot } from './api';

/**
 * Bridges `@xyflow/react`'s own theming variables to our semantic tokens.
 *
 * Same technique the admin workflow canvas uses: the library ships a light
 * palette and an un-branded dark one behind its own class, so setting the
 * variables here makes its chrome follow whatever `[data-theme]` resolves to
 * with no theme-aware JS branch.
 */
const CONTROLS_THEME_STYLE = {
  '--xy-controls-button-background-color': 'var(--surface)',
  '--xy-controls-button-background-color-hover': 'var(--surface-soft)',
  '--xy-controls-button-color': 'var(--text)',
  '--xy-controls-button-color-hover': 'var(--primary)',
  '--xy-controls-button-border-color': 'var(--border)',
} as CSSProperties;

const nodeTypes: NodeTypes = { canvasNode: CanvasNodeCard };

interface CanvasViewProps {
  /** Needed by the Agent card, which talks to a canvas-scoped route rather
   * than going through `onCommit` like every other card. */
  canvasId: string;
  graph: CanvasGraph;
  snapshot: CanvasSnapshot;
  readOnly?: boolean;
  /** Called with the whole graph after a committed change (drag released,
   * edge connected) — never on intermediate drag frames. */
  onCommit: (graph: CanvasGraph) => void;
  /** Turn a prompt node into a generation request. */
  onGenerate?: (node: CanvasFlowNode) => void;
  /** Attach a node's content to an episode. */
  onSendToSeries?: (node: CanvasFlowNode) => void;
  canSendToSeries?: boolean;
  /** A card now binds something the current `snapshot` does not describe, so
   * the shell must flush and re-hydrate.
   *
   * Fires for an upload (the signed URL only ever comes from the server), for
   * a director capture, and for a skill picked out of the prompt library.
   * Without the last one the freshly placed skill card renders as 已失效 until
   * the next full page load — hydration decides `stale` from `snapshot.skills`,
   * and the snapshot in hand predates the card. */
  onSnapshotStale?: () => void;
  /** Name used for the exported file. */
  exportName?: string;
  /** An unreadable or empty import file — surfaced by the shell as a toast. */
  onImportFailed?: () => void;
}

function CanvasViewInner({
  canvasId,
  graph,
  snapshot,
  readOnly = false,
  onCommit,
  onGenerate,
  onSendToSeries,
  canSendToSeries = false,
  onSnapshotStale,
  exportName = 'canvas',
  onImportFailed,
}: CanvasViewProps) {
  const [uploading, setUploading] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const { screenToFlowPosition } = useReactFlow();
  const converted = useMemo(() => graphToFlow(graph, snapshot), [graph, snapshot]);
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasFlowNode>(converted.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasFlowEdge>(converted.edges);

  // Adopting a new server document must not clobber an in-progress drag, so
  // the incoming graph is only applied when it actually differs from what is
  // rendered. Comparing the serialised form is cheap at these node counts and
  // avoids an identity-based effect that would fire on every parent render.
  const renderedRef = useRef('');
  useEffect(() => {
    const next = JSON.stringify(converted.nodes.map((n) => [n.id, n.position, n.data.stale]));
    if (next === renderedRef.current) return;
    renderedRef.current = next;
    // Merge, never replace wholesale. Hydration owns the *derived* fields
    // (`thumbnailUrl`, `stale`, `subtitle`); the person at the keyboard owns
    // the authored ones (`label`, `payload`) and the selection. Taking the
    // converted node whole discarded both: selecting a card and pausing
    // deselected it, and a snapshot refresh landing mid-edit wiped the name
    // that had just been typed.
    setNodes((current) => {
      const local = new Map(current.map((node) => [node.id, node] as const));
      return converted.nodes.map((node) => {
        const existing = local.get(node.id);
        if (!existing) return node;
        return {
          ...node,
          selected: existing.selected,
          data: {
            ...node.data,
            label: existing.data.label,
            payload: existing.data.payload,
          },
        };
      });
    });
    setEdges(converted.edges);
  }, [converted, setNodes, setEdges]);

  const commit = useCallback(
    (nextNodes: CanvasFlowNode[], nextEdges: CanvasFlowEdge[]) => {
      onCommit(flowToGraph(nextNodes, nextEdges));
    },
    [onCommit],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) => {
        const next = addEdge({ ...connection, id: newCanvasEdgeId() }, current);
        commit(nodes, next);
        return next;
      });
    },
    [commit, nodes, setEdges],
  );

  const addNode = useCallback(
    (kind: CanvasNodeKind, extra?: { label?: string; binding?: CanvasNodeBinding }) => {
      const rect = wrapperRef.current?.getBoundingClientRect();
      const centre = screenToFlowPosition({
        x: (rect?.left ?? 0) + (rect?.width ?? 0) / 2,
        y: (rect?.top ?? 0) + (rect?.height ?? 0) / 2,
      });
      // Find a free slot *inside the visible area*. Cascading blindly away
      // from existing cards pushed later ones below the fold — created, saved,
      // and invisible. Overlapping is also not an option: a covered card's
      // connection handles cannot be grabbed, so the two could never be wired
      // together. So: scan the on-screen region and take the first free cell.
      // Inset past the floating overlays before converting to flow space. The
      // toolbar sits top-left and the zoom controls / minimap along the
      // bottom; a card dropped under one of those cannot be clicked, and its
      // connection handles cannot be grabbed at all.
      const TOOLBAR_PX = 84;
      const BOTTOM_CHROME_PX = 140;
      const EDGE_PX = 24;
      const topLeft = screenToFlowPosition({
        x: (rect?.left ?? 0) + EDGE_PX,
        y: (rect?.top ?? 0) + TOOLBAR_PX,
      });
      const bottomRight = screenToFlowPosition({
        x: (rect?.left ?? 0) + (rect?.width ?? 0) - EDGE_PX,
        y: (rect?.top ?? 0) + (rect?.height ?? 0) - BOTTOM_CHROME_PX,
      });
      // Place each card beside the previous one, wrapping to the next row at
      // the right edge. Deterministic and always adjacent, which is what you
      // want for wiring two cards together — and unlike a collision search it
      // cannot drop a card under an overlay or off the bottom of the canvas.
      const COL = 280;
      const ROW = 260;
      const previous = nodes.at(-1);
      let position = { ...centre };
      if (previous) {
        position = { x: previous.position.x + COL, y: previous.position.y };
        if (position.x + COL > bottomRight.x) {
          position = { x: topLeft.x, y: previous.position.y + ROW };
        }
        if (position.y + ROW > bottomRight.y) {
          position.y = topLeft.y;
        }
      }
      const node: CanvasFlowNode = {
        id: newCanvasNodeId(),
        type: 'canvasNode',
        position,
        data: {
          kind,
          label: extra?.label ?? '',
          // Same reasoning as `addNodeAt`: hydration resolves the binding on
          // the next read, and calling a card broken for one render would be
          // a lie.
          stale: false,
          ...(extra?.binding ? { binding: extra.binding } : {}),
        },
      };
      const next = [...nodes, node];
      setNodes(next);
      commit(next, edges);
    },
    [commit, edges, nodes, screenToFlowPosition, setNodes],
  );

  /** Adds a card at an explicit screen point — the context menu's "add note"
   * drops it where the user right-clicked, not at the viewport centre. */
  const addNodeAt = useCallback(
    (
      kind: CanvasNodeKind,
      screenPoint: { x: number; y: number },
      extra?: { label?: string; binding?: CanvasNodeBinding },
    ) => {
      const node: CanvasFlowNode = {
        id: newCanvasNodeId(),
        type: 'canvasNode',
        position: screenToFlowPosition(screenPoint),
        data: {
          kind,
          label: extra?.label ?? '',
          // Not stale by construction: hydration resolves it on the next read,
          // and marking a card the user just dropped as broken would be a lie
          // for the one render before that lands.
          stale: false,
          ...(extra?.binding ? { binding: extra.binding } : {}),
        },
      };
      const next = [...nodes, node];
      setNodes(next);
      commit(next, edges);
    },
    [commit, edges, nodes, screenToFlowPosition, setNodes],
  );

  /** Drop a card the user dragged in from a panel.
   *
   * Shared channel: the prompt library drags skills, and the workbench drags
   * a result back. One handler, one payload format — see `canvas-dnd.ts`. */
  const onDrop = useCallback(
    (event: React.DragEvent) => {
      const payload = readCanvasDrag(event.dataTransfer);
      if (!payload) return;
      event.preventDefault();
      addNodeAt(payload.kind, { x: event.clientX, y: event.clientY }, payload);
    },
    [addNodeAt],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    // Only claim drags that are ours, so a file dragged onto the canvas still
    // reaches whatever else wants it.
    if (!hasCanvasDrag(event.dataTransfer)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const editing = useCanvasEditing({
    nodes,
    edges,
    setNodes,
    setEdges,
    commit,
    disabled: readOnly,
  });
  // Destructured rather than used as `editing.x`: the hook returns a fresh
  // object each render, so depending on it defeats every `useCallback` below.
  const {
    apply: applyEdit,
    patchNode,
    commitCurrent,
    undo,
    redo,
    copy,
    paste,
    duplicate,
    removeSelected,
    canUndo,
    canRedo,
    canPaste,
  } = editing;

  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const [directorOpen, setDirectorOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);

  /** React Flow reports a resize as a `dimensions` change, flagging the last
   * one with `resizing: false`. Persisting on that — rather than on every
   * intermediate frame — makes a resize one save, like a drag. */
  const handleNodesChange = useCallback<typeof onNodesChange>(
    (changes) => {
      onNodesChange(changes);
      const finished = changes.some(
        (change) => change.type === 'dimensions' && change.resizing === false,
      );
      if (finished) {
        queueMicrotask(() => commitCurrent());
      }
    },
    [commitCurrent, onNodesChange],
  );

  const exportCanvas = useCallback(() => {
    const blob = new Blob([serializeCanvas(exportName, flowToGraph(nodes, edges))], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${exportName || 'canvas'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [edges, exportName, nodes]);

  const importCanvas = useCallback(
    (file: File) => {
      void file
        .text()
        .then((raw) => {
          // Imported cards are offset so they land beside what is already
          // here rather than on top of it, and `parseCanvasFile` has already
          // given them fresh ids and dropped the exporter's domain bindings.
          const incoming = offsetGraph(parseCanvasFile(raw), 40, 40);
          const merged = graphToFlow(incoming, snapshot);
          applyEdit([...nodes, ...merged.nodes], [...edges, ...merged.edges]);
        })
        .catch(() => onImportFailed?.());
    },
    [applyEdit, edges, nodes, onImportFailed, snapshot],
  );

  const selectedCount = nodes.filter((n) => n.selected).length;
  const selectedNode = nodes.find((n) => n.selected) ?? null;

  // Deliberately not `useCallback`: React Compiler cannot preserve manual
  // memoization across this async chain, and it optimizes the plain
  // function on its own.
  const uploadToNode = (node: CanvasFlowNode, file: File) => {
    setUploading(true);
    // `generation_reference` rather than a canvas-specific purpose: to the
    // rest of the platform this is exactly what it is — a picture the user
    // may hand to a generation. A dedicated purpose would mean four more
    // places to keep in step for no behavioural difference.
    void uploadFile(file, 'generation_reference')
      .then((asset) => {
        // Through `apply`, so attaching a picture is undoable like any other
        // change to the board.
        applyEdit(
          nodes.map((current) =>
            current.id === node.id
              ? {
                  ...current,
                  data: {
                    ...current.data,
                    binding: { kind: current.data.kind, asset_id: asset.id },
                    // Shown straight away; the durable URL arrives with the
                    // next hydration.
                    thumbnailUrl: asset.url ?? null,
                  },
                }
              : current,
          ),
          edges,
        );
        onSnapshotStale?.();
      })
      .finally(() => setUploading(false));
  };

  const referenceCount = selectedNode
    ? upstreamAssetIds(selectedNode.id, flowToGraph(nodes, edges)).length
    : 0;

  return (
    <div className="flex h-full w-full">
      <div ref={wrapperRef} className="min-w-0 flex-1" data-testid="canvas-surface">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onDrop={readOnly ? undefined : onDrop}
          onDragOver={readOnly ? undefined : onDragOver}
          onNodesChange={readOnly ? undefined : handleNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          // Committing on drag *stop* rather than on every change keeps one
          // gesture to one save and one undo step.
          onNodeDragStop={readOnly ? undefined : () => commit(nodes, edges)}
          onNodeContextMenu={
            readOnly
              ? undefined
              : (event, node) => {
                  event.preventDefault();
                  // Right-clicking an unselected card selects it first, so the
                  // menu's actions apply to what was actually clicked.
                  if (!node.selected) {
                    setNodes(nodes.map((n) => ({ ...n, selected: n.id === node.id })));
                  }
                  setMenu({
                    x: event.clientX,
                    y: event.clientY,
                    nodeId: node.id,
                    hasSelection: true,
                  });
                }
          }
          onPaneContextMenu={
            readOnly
              ? undefined
              : (event) => {
                  event.preventDefault();
                  const point = 'clientX' in event ? event : null;
                  if (point) {
                    setMenu({
                      x: point.clientX,
                      y: point.clientY,
                      nodeId: null,
                      hasSelection: selectedCount > 0,
                    });
                  }
                }
          }
          onConnect={readOnly ? undefined : onConnect}
          nodeTypes={nodeTypes}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          elementsSelectable
          // Deletion goes through the toolbar, which can ask about the domain
          // object behind the node. A raw Delete keypress while a field is
          // focused must never remove a card.
          deleteKeyCode={[]}
          fitView
          // Cap the initial zoom: fitting a canvas that holds one card blows it
          // up to the maximum, which looks broken and leaves no room to place
          // the next card beside it.
          fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          style={CONTROLS_THEME_STYLE}
        >
          <Background />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!bg-surface" />
          {readOnly ? null : (
            <Panel position="top-left">
              <div className="flex flex-col items-start gap-2">
                <CanvasToolbar
                  onAdd={addNode}
                  onDeleteSelected={removeSelected}
                  selectedCount={selectedCount}
                  onUndo={undo}
                  onRedo={redo}
                  canUndo={canUndo}
                  canRedo={canRedo}
                  onExport={exportCanvas}
                  onImport={importCanvas}
                  onOpenDirector={() => setDirectorOpen(true)}
                  onToggleLibrary={() => setLibraryOpen((open) => !open)}
                  libraryOpen={libraryOpen}
                />
                {/* Inside the surface rather than in the page header, unlike
                    the workbench: picking a skill has to place a card, and
                    only what sits under `ReactFlowProvider` can turn a
                    viewport into a position. */}
                {libraryOpen ? (
                  <PromptLibraryPanel
                    onPick={(skill) => {
                      addNode('skill', {
                        label: skill.title,
                        binding: { kind: 'skill', skill_id: skill.id },
                      });
                      // The snapshot in hand does not know this skill, and
                      // hydration reads `stale` from it — without the
                      // re-read the card the user just placed comes back
                      // dimmed and marked broken.
                      onSnapshotStale?.();
                    }}
                  />
                ) : null}
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
      <DirectorDialog
        open={directorOpen}
        onClose={() => setDirectorOpen(false)}
        snapshot={snapshot}
        onCaptured={(asset, framingPrompt) => {
          // The shot lands as a picture card carrying the asset, and a prompt
          // card holding how it was framed, already wired together — the same
          // reference relationship any hand-built pair would have.
          const rect = wrapperRef.current?.getBoundingClientRect();
          const at = screenToFlowPosition({
            x: (rect?.left ?? 0) + (rect?.width ?? 0) / 2,
            y: (rect?.top ?? 0) + (rect?.height ?? 0) / 2,
          });
          const shot: CanvasFlowNode = {
            id: newCanvasNodeId(),
            type: 'canvasNode',
            position: at,
            data: {
              kind: 'image',
              label: '',
              stale: false,
              binding: { kind: 'image', asset_id: asset.id },
              thumbnailUrl: asset.url ?? null,
            },
          };
          const shotPrompt: CanvasFlowNode = {
            id: newCanvasNodeId(),
            type: 'canvasNode',
            position: { x: at.x + 300, y: at.y },
            data: { kind: 'prompt', label: '', stale: false, payload: { text: framingPrompt } },
          };
          applyEdit(
            [...nodes, shot, shotPrompt],
            [...edges, { id: newCanvasEdgeId(), source: shot.id, target: shotPrompt.id }],
          );
          onSnapshotStale?.();
        }}
      />
      <CanvasContextMenu
        state={menu}
        onClose={() => setMenu(null)}
        onAddNote={(at) => addNodeAt('note', at)}
        onCopy={copy}
        onDuplicate={duplicate}
        onPaste={() => paste()}
        onDelete={removeSelected}
        canPaste={canPaste}
      />
      {readOnly ? null : (
        <CanvasProperties
          canvasId={canvasId}
          node={selectedNode}
          onPatch={patchNode}
          onGenerate={onGenerate}
          onSendToSeries={onSendToSeries}
          canSendToSeries={canSendToSeries}
          onUpload={uploadToNode}
          uploading={uploading}
          referenceCount={referenceCount}
        />
      )}
    </div>
  );
}

export function CanvasView(props: CanvasViewProps) {
  return (
    <ReactFlowProvider>
      <CanvasViewInner {...props} />
    </ReactFlowProvider>
  );
}
