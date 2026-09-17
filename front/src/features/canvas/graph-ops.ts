/**
 * Turning "here is the graph I want" into "here is what changed".
 *
 * The rest of the canvas thinks in documents: `use-canvas-editing.ts` hands
 * around whole `CanvasGraph`s, undo/redo swaps between them, and every commit
 * is a complete arrangement. That is the right model for a UI. It is the wrong
 * model for the wire, because a whole-document write gives the browser and the
 * server one cell to fight over, and the server has to be able to land a
 * generated card while someone is dragging.
 *
 * So this module sits between the two: the client keeps its documents, and
 * `diffGraph` reduces the difference between the last acknowledged server
 * state and the desired one to a list of per-entity operations. Diffing
 * against the *acknowledged* state rather than the previous local one is what
 * collapses "create a card, then drag it four times" into a single create at
 * the final position.
 */

import type {
  CanvasChange,
  CanvasEdge,
  CanvasGraph,
  CanvasNode,
  CanvasNodeBinding,
  CanvasOp,
} from './api';

let opCounter = 0;

function newOpId(): string {
  opCounter += 1;
  return `op_${Date.now().toString(36)}_${opCounter.toString(36)}`;
}

/** A node the client minted but the server has not acknowledged yet. */
export const UNSAVED_REVISION = 0;

function samePosition(a: CanvasNode, b: CanvasNode): boolean {
  // Rounded because the server stores integers; a sub-pixel drag that rounds
  // to the same coordinate is not a change and must not cost a round trip.
  return (
    Math.round(a.position.x) === Math.round(b.position.x) &&
    Math.round(a.position.y) === Math.round(b.position.y)
  );
}

function sameSize(a: CanvasNode, b: CanvasNode): boolean {
  const left = a.size ?? null;
  const right = b.size ?? null;
  if (left === null || right === null) return left === right;
  return (
    Math.round(left.width) === Math.round(right.width) &&
    Math.round(left.height) === Math.round(right.height)
  );
}

/** Structural equality by serialisation.
 *
 * Adequate here and nowhere near as fragile as it looks: both sides originate
 * as JSON from the same code paths, so key order is stable, and the payloads
 * are small. A hand-written deep compare would be more code for no benefit.
 */
function sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

function byId<T extends { id: string }>(items: readonly T[]): Map<string, T> {
  return new Map(items.map((item) => [item.id, item]));
}

/**
 * Operations that carry `base` to `next`.
 *
 * Order matters and is deliberate: creates first, then updates, then deletes.
 * An edge can only be created once both its endpoints exist, and a node can
 * only be deleted after the edges referencing it are gone — the server cascades
 * those, but emitting the deletes in this order keeps a partially-applied batch
 * from ever describing a graph with a dangling edge.
 */
export function diffGraph(base: CanvasGraph, next: CanvasGraph): CanvasOp[] {
  const baseNodes = byId(base.nodes);
  const nextNodes = byId(next.nodes);
  const baseEdges = byId(base.edges);
  const nextEdges = byId(next.edges);

  const creates: CanvasOp[] = [];
  const updates: CanvasOp[] = [];
  const deletes: CanvasOp[] = [];

  for (const node of next.nodes) {
    const previous = baseNodes.get(node.id);
    if (!previous) {
      creates.push({ op_id: newOpId(), kind: 'node.create', node });
      continue;
    }

    const op: Extract<CanvasOp, { kind: 'node.update' }> = {
      op_id: newOpId(),
      kind: 'node.update',
      node_id: node.id,
      expected_revision: previous.revision ?? UNSAVED_REVISION,
    };
    let changed = false;
    if (!samePosition(previous, node)) {
      op.position = {
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
      };
      changed = true;
    }
    if (!sameSize(previous, node)) {
      op.size = node.size
        ? { width: Math.round(node.size.width), height: Math.round(node.size.height) }
        : null;
      changed = true;
    }
    if ((previous.z_index ?? 0) !== (node.z_index ?? 0)) {
      op.z_index = node.z_index ?? 0;
      changed = true;
    }
    if (!sameJson(previous.binding, node.binding)) {
      op.binding = (node.binding ?? null) as CanvasNodeBinding | null;
      changed = true;
    }
    if (!sameJson(previous.data, node.data)) {
      op.data = node.data ?? {};
      changed = true;
    }
    // Only send fields that actually moved. A `node.update` carrying nothing
    // would still cost a sequence number and a change-feed row for no reason.
    if (changed) updates.push(op);
  }

  for (const node of base.nodes) {
    if (nextNodes.has(node.id)) continue;
    deletes.push({
      op_id: newOpId(),
      kind: 'node.delete',
      node_id: node.id,
      expected_revision: node.revision ?? UNSAVED_REVISION,
    });
  }

  for (const edge of next.edges) {
    if (baseEdges.has(edge.id)) continue;
    creates.push({ op_id: newOpId(), kind: 'edge.create', edge });
  }

  for (const edge of base.edges) {
    if (nextEdges.has(edge.id)) continue;
    // Emitted before node deletes so the wire order never implies a graph
    // where an edge outlives an endpoint.
    deletes.unshift({ op_id: newOpId(), kind: 'edge.delete', edge_id: edge.id });
  }

  return [...creates, ...updates, ...deletes];
}

function nodeFromPayload(payload: Record<string, unknown>): CanvasNode | null {
  const id = payload.id;
  const kind = payload.kind;
  const position = payload.position as { x: number; y: number } | undefined;
  if (typeof id !== 'string' || typeof kind !== 'string' || !position) return null;
  return {
    id,
    kind: kind as CanvasNode['kind'],
    position,
    size: (payload.size ?? null) as CanvasNode['size'],
    z_index: typeof payload.z_index === 'number' ? payload.z_index : 0,
    binding: (payload.binding ?? null) as CanvasNode['binding'],
    data: (payload.data ?? {}) as Record<string, unknown>,
    origin: (payload.origin ?? 'user') as CanvasNode['origin'],
    revision: typeof payload.revision === 'number' ? payload.revision : 1,
  };
}

function edgeFromPayload(payload: Record<string, unknown>): CanvasEdge | null {
  const id = payload.id;
  const source = payload.source;
  const target = payload.target;
  if (typeof id !== 'string' || typeof source !== 'string' || typeof target !== 'string') {
    return null;
  }
  return {
    id,
    source,
    target,
    source_handle: (payload.source_handle ?? null) as string | null,
    target_handle: (payload.target_handle ?? null) as string | null,
    kind: typeof payload.kind === 'string' ? payload.kind : 'link',
  };
}

/**
 * Fold the server's change feed into a graph.
 *
 * The server is authoritative for every entity it reports, which is what makes
 * this safe to run over the graph the client just sent: its own writes come
 * back with real revisions and replace the optimistic local copies, another
 * session's edits arrive the same way, and a delete removes the card whether
 * or not this client knew it was gone.
 */
export function applyChanges(graph: CanvasGraph, changes: readonly CanvasChange[]): CanvasGraph {
  if (changes.length === 0) return graph;

  const nodes = byId(graph.nodes);
  const edges = byId(graph.edges);

  for (const change of changes) {
    if (change.entity_type === 'node') {
      if (change.action === 'deleted') {
        nodes.delete(change.entity_id);
        // The server cascades a node's edges and logs each one, but a client
        // that has the node and not those log entries would keep drawing
        // lines into nothing. Dropping them here makes the fold total.
        for (const [edgeId, edge] of edges) {
          if (edge.source === change.entity_id || edge.target === change.entity_id) {
            edges.delete(edgeId);
          }
        }
        continue;
      }
      const node = nodeFromPayload(change.payload);
      if (node) nodes.set(node.id, node);
    } else if (change.entity_type === 'edge') {
      if (change.action === 'deleted') {
        edges.delete(change.entity_id);
        continue;
      }
      const edge = edgeFromPayload(change.payload);
      if (edge) edges.set(edge.id, edge);
    }
    // `agent_run` / `agent_task` changes are not graph entities; the workbench
    // panel consumes those from the same feed.
  }

  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** The graph as the server currently has it. */
export function graphFromProject(project: {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}): CanvasGraph {
  return { nodes: project.nodes, edges: project.edges };
}
