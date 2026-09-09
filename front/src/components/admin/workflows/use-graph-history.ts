'use client';

import { useCallback, useRef, useState } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { WorkflowEdgeData } from '@/components/admin/workflows/workflow-edge';
import type { WorkflowNodeData } from '@/components/admin/workflows/workflow-node';

/** Generic over the node/edge payloads so a second canvas (the consumer-facing
 * `features/canvas`) can share this stack instead of copying it. Defaults keep
 * the admin workflow editor's call sites unchanged. */
export interface GraphSnapshotOf<
  NodeData extends Record<string, unknown>,
  EdgeData extends Record<string, unknown>,
> {
  nodes: Node<NodeData>[];
  edges: Edge<EdgeData>[];
}

export type GraphSnapshot = GraphSnapshotOf<WorkflowNodeData, WorkflowEdgeData>;

/**
 * Undo/redo for the canvas.
 *
 * Snapshots are pushed by the callers that make a *committed* change — adding
 * or deleting a node, connecting, editing config, finishing a drag — never on
 * every intermediate frame of a drag, which would make one gesture take
 * dozens of Ctrl+Z presses to reverse.
 *
 * Snapshots are shallow copies of the two arrays. Node `data` objects are
 * replaced rather than mutated everywhere in this editor (`{...node, data:
 * {...}}`), so an old snapshot keeps pointing at the old data.
 */
export function useGraphHistory<
  NodeData extends Record<string, unknown> = WorkflowNodeData,
  EdgeData extends Record<string, unknown> = WorkflowEdgeData,
>(limit = 50) {
  type Snapshot = GraphSnapshotOf<NodeData, EdgeData>;
  const past = useRef<Snapshot[]>([]);
  const future = useRef<Snapshot[]>([]);
  // Only to re-render the toolbar's enabled state; the stacks themselves stay
  // in refs so pushing during a React event never schedules an extra render.
  const [depths, setDepths] = useState({ past: 0, future: 0 });

  const sync = useCallback(() => {
    setDepths({ past: past.current.length, future: future.current.length });
  }, []);

  const commit = useCallback(
    (snapshot: Snapshot) => {
      past.current = [...past.current.slice(-(limit - 1)), snapshot];
      future.current = [];
      sync();
    },
    [limit, sync],
  );

  const undo = useCallback(
    (current: Snapshot): Snapshot | null => {
      const previous = past.current.at(-1);
      if (!previous) return null;
      past.current = past.current.slice(0, -1);
      future.current = [...future.current, current];
      sync();
      return previous;
    },
    [sync],
  );

  const redo = useCallback(
    (current: Snapshot): Snapshot | null => {
      const next = future.current.at(-1);
      if (!next) return null;
      future.current = future.current.slice(0, -1);
      past.current = [...past.current, current];
      sync();
      return next;
    },
    [sync],
  );

  return { commit, undo, redo, canUndo: depths.past > 0, canRedo: depths.future > 0 };
}
