'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useGraphHistory } from '@/components/admin/workflows/use-graph-history';

import { newCanvasEdgeId, newCanvasNodeId } from './graph-convert';
import type { CanvasFlowEdge, CanvasFlowNode } from './graph-convert';

/** Where a pasted or duplicated copy lands relative to its original. */
const PASTE_OFFSET = 32;

interface Options {
  nodes: CanvasFlowNode[];
  edges: CanvasFlowEdge[];
  setNodes: (nodes: CanvasFlowNode[]) => void;
  setEdges: (edges: CanvasFlowEdge[]) => void;
  /** Persist a committed change. Never called for intermediate drag frames. */
  commit: (nodes: CanvasFlowNode[], edges: CanvasFlowEdge[]) => void;
  /** Keyboard shortcuts are ignored while true. */
  disabled?: boolean;
}

/**
 * The editing primitives every canvas is expected to have: undo/redo, a
 * clipboard, duplication, select-all and the keyboard map that reaches them.
 *
 * Kept out of `canvas-view.tsx` so that file stays about rendering. History
 * reuses the admin workflow editor's stack (`useGraphHistory`) rather than a
 * second implementation — it was made generic for exactly this.
 */
export function useCanvasEditing({
  nodes,
  edges,
  setNodes,
  setEdges,
  commit,
  disabled = false,
}: Options) {
  const history = useGraphHistory<CanvasFlowNode['data'], Record<string, unknown>>();

  // Live state for the keyboard handler, which is bound once to `window` and
  // would otherwise capture the arrays from the render it was attached in.
  const stateRef = useRef({ nodes, edges });
  useEffect(() => {
    stateRef.current = { nodes, edges };
  }, [nodes, edges]);

  const clipboardRef = useRef<{ nodes: CanvasFlowNode[]; edges: CanvasFlowEdge[] } | null>(null);
  // Mirrored into state purely so the context menu can grey out "paste"; the
  // ref stays the source of truth for the handlers themselves.
  const [hasClipboard, setHasClipboard] = useState(false);

  /** Snapshot *before* mutating, so undo returns to the pre-change state. */
  const apply = useCallback(
    (nextNodes: CanvasFlowNode[], nextEdges: CanvasFlowEdge[]) => {
      const { nodes: prevNodes, edges: prevEdges } = stateRef.current;
      history.commit({ nodes: prevNodes, edges: prevEdges });
      setNodes(nextNodes);
      setEdges(nextEdges);
      commit(nextNodes, nextEdges);
    },
    [commit, history, setEdges, setNodes],
  );

  const undo = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    const previous = history.undo({ nodes: current, edges: currentEdges });
    if (!previous) return;
    setNodes(previous.nodes);
    setEdges(previous.edges);
    commit(previous.nodes, previous.edges);
  }, [commit, history, setEdges, setNodes]);

  const redo = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    const next = history.redo({ nodes: current, edges: currentEdges });
    if (!next) return;
    setNodes(next.nodes);
    setEdges(next.edges);
    commit(next.nodes, next.edges);
  }, [commit, history, setEdges, setNodes]);

  const copy = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    const picked = current.filter((node) => node.selected);
    if (picked.length === 0) return;
    const ids = new Set(picked.map((node) => node.id));
    clipboardRef.current = {
      nodes: picked,
      // Only edges wholly inside the selection: half an edge cannot be pasted.
      edges: currentEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    };
    setHasClipboard(true);
  }, []);

  /** Shared by paste and duplicate — both are "copy these, offset, new ids". */
  const cloneInto = useCallback(
    (source: { nodes: CanvasFlowNode[]; edges: CanvasFlowEdge[] }) => {
      if (source.nodes.length === 0) return;
      const { nodes: current, edges: currentEdges } = stateRef.current;
      const remap = new Map<string, string>();
      const copies = source.nodes.map((node) => {
        const id = newCanvasNodeId();
        remap.set(node.id, id);
        return {
          ...node,
          id,
          position: { x: node.position.x + PASTE_OFFSET, y: node.position.y + PASTE_OFFSET },
          selected: true,
          // A copy is a fresh card, never a second claim on the same domain
          // object: two nodes bound to one episode would both try to own it.
          data: { ...node.data, binding: undefined },
        };
      });
      const copiedEdges = source.edges.map((edge) => ({
        ...edge,
        id: newCanvasEdgeId(),
        source: remap.get(edge.source) ?? edge.source,
        target: remap.get(edge.target) ?? edge.target,
      }));
      apply(
        [...current.map((node) => ({ ...node, selected: false })), ...copies],
        [...currentEdges, ...copiedEdges],
      );
    },
    [apply],
  );

  const paste = useCallback(() => {
    if (clipboardRef.current) cloneInto(clipboardRef.current);
  }, [cloneInto]);

  const duplicate = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    const picked = current.filter((node) => node.selected);
    if (picked.length === 0) return;
    const ids = new Set(picked.map((node) => node.id));
    cloneInto({
      nodes: picked,
      edges: currentEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    });
  }, [cloneInto]);

  const selectAll = useCallback(() => {
    const { nodes: current } = stateRef.current;
    setNodes(current.map((node) => ({ ...node, selected: true })));
  }, [setNodes]);

  /** Persist exactly what is on screen now. Used by anything whose "done"
   * moment is not a React event with the arrays to hand — a node resize
   * finishing, for instance. */
  const commitCurrent = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    commit(current, currentEdges);
  }, [commit]);

  /**
   * Edits one card's authored fields.
   *
   * The local update is immediate so the field stays responsive, and the save
   * is debounced. Two things this must get right, both learned the hard way:
   * the timer commits **current** state (committing the array captured at
   * keystroke time silently reverted anything added in between), and unmount
   * *flushes* rather than clearing (clearing threw away whatever had just been
   * typed if the user navigated inside the window).
   */
  const patchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPatchRef = useRef<(() => void) | null>(null);
  const patchNode = useCallback(
    (nodeId: string, patch: { label?: string; text?: string; camera?: unknown }) => {
      const { nodes: current } = stateRef.current;
      setNodes(
        current.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  ...(patch.label !== undefined ? { label: patch.label } : {}),
                  ...(patch.text !== undefined || patch.camera !== undefined
                    ? {
                        payload: {
                          ...(node.data.payload ?? {}),
                          ...(patch.text !== undefined ? { text: patch.text } : {}),
                          ...(patch.camera !== undefined ? { camera: patch.camera } : {}),
                        },
                      }
                    : {}),
                },
              }
            : node,
        ),
      );
      if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
      const flush = () => {
        pendingPatchRef.current = null;
        commitCurrent();
      };
      pendingPatchRef.current = flush;
      patchTimerRef.current = setTimeout(flush, 600);
    },
    [commitCurrent, setNodes],
  );

  useEffect(
    () => () => {
      if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
      pendingPatchRef.current?.();
    },
    [],
  );

  const removeSelected = useCallback(() => {
    const { nodes: current, edges: currentEdges } = stateRef.current;
    const doomed = new Set(current.filter((node) => node.selected).map((node) => node.id));
    if (doomed.size === 0) return;
    apply(
      current.filter((node) => !doomed.has(node.id)),
      // Edges touching a removed card go with it, or the next load drops them
      // silently as dangling.
      currentEdges.filter((edge) => !doomed.has(edge.source) && !doomed.has(edge.target)),
    );
  }, [apply]);

  useEffect(() => {
    if (disabled) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      // Never steal a keystroke aimed at a field — the properties panel sits
      // beside the canvas, so typing a prompt must not delete the card.
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      const mod = event.metaKey || event.ctrlKey;

      if (mod && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (mod && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redo();
        return;
      }
      if (mod && event.key.toLowerCase() === 'c') {
        copy();
        return;
      }
      if (mod && event.key.toLowerCase() === 'v') {
        event.preventDefault();
        paste();
        return;
      }
      if (mod && event.key.toLowerCase() === 'd') {
        event.preventDefault();
        duplicate();
        return;
      }
      if (mod && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        selectAll();
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        removeSelected();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [copy, disabled, duplicate, paste, redo, removeSelected, selectAll, undo]);

  return {
    apply,
    undo,
    redo,
    copy,
    paste,
    duplicate,
    selectAll,
    removeSelected,
    canUndo: history.canUndo,
    canRedo: history.canRedo,
    canPaste: hasClipboard,
    patchNode,
    commitCurrent,
  };
}
