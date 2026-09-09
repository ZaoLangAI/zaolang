import type { CanvasGraph, CanvasNode } from './api';
import { newCanvasEdgeId, newCanvasNodeId } from './graph-convert';

/** Bumped only when the on-disk shape changes in a way an older file would be
 * read wrongly under. Reading tolerates a missing version (the first export
 * predates this field). */
export const CANVAS_FILE_VERSION = 1;

export interface CanvasFile {
  version: number;
  title: string;
  graph: CanvasGraph;
}

export function serializeCanvas(title: string, graph: CanvasGraph): string {
  const file: CanvasFile = { version: CANVAS_FILE_VERSION, title, graph };
  return JSON.stringify(file, null, 2);
}

/**
 * Reads an exported canvas back.
 *
 * Every node and edge is given a **fresh id**. An import is a copy, not a
 * restore: pasting a file into a canvas that already holds the original would
 * otherwise produce duplicate ids, and the server rejects those outright.
 *
 * Domain bindings are dropped on purpose. They point at episodes, drafts and
 * assets belonging to whoever exported the file — carrying them over would
 * either dangle (the objects are not in this canvas' series) or, worse, look
 * like a live link to content the importer cannot actually see. What survives
 * is the arrangement: the cards, their text, and how they are wired.
 */
export function parseCanvasFile(raw: string): CanvasGraph {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('invalid-json');
  }
  if (typeof parsed !== 'object' || parsed === null) throw new Error('invalid-shape');
  const graph = (parsed as { graph?: unknown }).graph;
  if (typeof graph !== 'object' || graph === null) throw new Error('invalid-shape');
  const rawNodes = (graph as { nodes?: unknown }).nodes;
  const rawEdges = (graph as { edges?: unknown }).edges;
  if (!Array.isArray(rawNodes)) throw new Error('invalid-shape');

  const remap = new Map<string, string>();
  const nodes: CanvasNode[] = [];
  for (const node of rawNodes) {
    if (typeof node !== 'object' || node === null) continue;
    const source = node as Partial<CanvasNode> & { id?: unknown };
    if (typeof source.id !== 'string' || typeof source.kind !== 'string') continue;
    const id = newCanvasNodeId();
    remap.set(source.id, id);
    nodes.push({
      id,
      kind: source.kind as CanvasNode['kind'],
      position: {
        x: Number(source.position?.x) || 0,
        y: Number(source.position?.y) || 0,
      },
      ...(source.size ? { size: source.size } : {}),
      data: typeof source.data === 'object' && source.data !== null ? source.data : {},
    });
  }

  const edges = (Array.isArray(rawEdges) ? rawEdges : [])
    .map((edge) => {
      if (typeof edge !== 'object' || edge === null) return null;
      const source = remap.get(String((edge as { source?: unknown }).source));
      const target = remap.get(String((edge as { target?: unknown }).target));
      if (!source || !target) return null;
      return { id: newCanvasEdgeId(), source, target, kind: 'link' };
    })
    .filter((edge): edge is NonNullable<typeof edge> => edge !== null);

  if (nodes.length === 0) throw new Error('empty');
  return { nodes, edges };
}

/** Offsets an imported graph so it lands beside what is already on the canvas
 * instead of on top of it. */
export function offsetGraph(graph: CanvasGraph, dx: number, dy: number): CanvasGraph {
  return {
    nodes: graph.nodes.map((node) => ({
      ...node,
      position: { x: node.position.x + dx, y: node.position.y + dy },
    })),
    edges: graph.edges,
  };
}
