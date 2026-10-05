import type { Edge, Node } from '@xyflow/react';

import type {
  AssetEdge,
  AssetEntry,
  AssetGraph,
  AssetGraphPendingJob,
  AssetRelation,
  AssetVariant,
} from '@/lib/api/types';

import type { CardKind } from '@/components/library/entry-actions';

/**
 * Pure mapping from the `/graph` payload to React Flow nodes and edges (no
 * positions — `layout.ts` adds them). Two levels:
 *
 * - every look / variant is a top-level "class box" node (`v:<id>`);
 * - an *expanded* look also gets one child node per image (`e:<id>`, React
 *   Flow `parentId`), laid out in a grid inside it.
 *
 * Image-level edges connect image nodes when both ends are visible. When
 * either end's look is collapsed they fold into one dotted "hint" edge
 * between the two looks (none when both images sit in the same look), so a
 * collapsed graph still shows where images were derived from.
 */

export type GraphSelection =
  | { type: 'card' }
  | { type: 'variant'; id: string }
  | { type: 'entry'; id: string }
  | { type: 'edge'; id: string };

export const variantNodeId = (id: string) => `v:${id}`;
export const entryNodeId = (id: string) => `e:${id}`;
export const pendingNodeId = (id: string) => `p:${id}`;

export function parseNodeId(
  nodeId: string,
): { kind: 'variant' | 'entry' | 'pending'; id: string } | null {
  const [prefix, ...rest] = nodeId.split(':');
  const id = rest.join(':');
  if (!id) return null;
  if (prefix === 'v') return { kind: 'variant', id };
  if (prefix === 'e') return { kind: 'entry', id };
  if (prefix === 'p') return { kind: 'pending', id };
  return null;
}

// ---- sizing (the node components render to exactly these) -----------------

export const LOOK_WIDTH = 288;
export const LOOK_HEADER = 52;
export const LOOK_ROW = 20;
export const LOOK_ROWS_PAD = 10;
export const LOOK_STRIP = 72;
export const LOOK_FOOTER = 36;
export const MAX_LOOK_ROWS = 6;
export const STRIP_THUMBS = 5;
export const ENTRY_WIDTH = 104;
export const ENTRY_HEIGHT = 132;
export const ENTRY_GAP = 10;
export const ENTRY_COLUMNS = 3;
export const GROUP_PAD = 12;
export const EMPTY_GROUP_HEIGHT = 48;

export type AttributeRowKey =
  | 'age_stage'
  | 'period'
  | 'outfit'
  | 'state'
  | 'scene_note'
  | 'scene'
  | 'lighting'
  | 'weather'
  | 'scene_state'
  | 'custom';

export interface AttributeRow {
  key: AttributeRowKey;
  /** Custom rows: the author's own attribute name. */
  name?: string;
  value: string;
}

/** A look's "class rows", in a fixed order; empty attributes are skipped. */
export function attributeRows(variant: AssetVariant, kind: CardKind): AttributeRow[] {
  const presets = (variant.presets ?? {}) as Record<string, string | null | undefined>;
  const attributes = variant.attributes ?? { custom: [] };
  const rows: AttributeRow[] = [];
  const push = (key: AttributeRowKey, value: string | null | undefined) => {
    if (value) rows.push({ key, value });
  };
  if (kind === 'character') {
    push('age_stage', presets.age_stage);
    push('period', presets.period);
    push('outfit', attributes.outfit);
    push('state', attributes.state);
    push('scene', variant.scene_link?.scene_name);
    push('scene_note', attributes.scene_note);
  } else {
    push('lighting', presets.lighting);
    push('weather', presets.weather);
    push('scene_state', presets.state);
    push('period', presets.period);
  }
  for (const item of attributes.custom ?? []) {
    rows.push({ key: 'custom', name: item.key, value: item.value });
  }
  return rows;
}

function shownRowCount(rows: AttributeRow[]): number {
  return rows.length > MAX_LOOK_ROWS ? MAX_LOOK_ROWS + 1 : rows.length;
}

export function isApprovedEntry(entry: AssetEntry): boolean {
  return entry.status !== 'candidate';
}

export function lookSize(
  variant: AssetVariant,
  kind: CardKind,
  expanded: boolean,
  extraEntries = 0,
): { width: number; height: number } {
  const rows = shownRowCount(attributeRows(variant, kind));
  const head = LOOK_HEADER + (rows ? rows * LOOK_ROW + LOOK_ROWS_PAD : 0);
  if (!expanded) return { width: LOOK_WIDTH, height: head + LOOK_STRIP + LOOK_FOOTER };
  const count = (variant.entries ?? []).length + extraEntries;
  const gridRows = Math.ceil(count / ENTRY_COLUMNS);
  const width = Math.max(
    LOOK_WIDTH,
    GROUP_PAD * 2 + ENTRY_COLUMNS * ENTRY_WIDTH + (ENTRY_COLUMNS - 1) * ENTRY_GAP,
  );
  const grid = count
    ? GROUP_PAD + gridRows * ENTRY_HEIGHT + (gridRows - 1) * ENTRY_GAP + GROUP_PAD
    : EMPTY_GROUP_HEIGHT;
  return { width, height: head + grid + LOOK_FOOTER };
}

/** Top-left of the `index`th child inside an expanded look. */
export function childPosition(
  variant: AssetVariant,
  kind: CardKind,
  index: number,
): { x: number; y: number } {
  const rows = shownRowCount(attributeRows(variant, kind));
  const head = LOOK_HEADER + (rows ? rows * LOOK_ROW + LOOK_ROWS_PAD : 0);
  const column = index % ENTRY_COLUMNS;
  const row = Math.floor(index / ENTRY_COLUMNS);
  return {
    x: GROUP_PAD + column * (ENTRY_WIDTH + ENTRY_GAP),
    y: head + GROUP_PAD + row * (ENTRY_HEIGHT + ENTRY_GAP),
  };
}

// ---- nodes & edges -----------------------------------------------------------

export interface LookNodeData extends Record<string, unknown> {
  variant: AssetVariant;
  kind: CardKind;
  rows: AttributeRow[];
  expanded: boolean;
  anchorEntryId: string | null;
  pendingCount: number;
  width: number;
  height: number;
  onToggle: (variantId: string) => void;
}

export interface EntryNodeData extends Record<string, unknown> {
  entry: AssetEntry;
  isAnchor: boolean;
}

export interface PendingNodeData extends Record<string, unknown> {
  job: AssetGraphPendingJob;
}

export interface RelationEdgeData extends Record<string, unknown> {
  relations: AssetRelation[];
  label?: string | null;
  origin?: 'auto' | 'manual';
  /** A folded image-level edge between two collapsed looks. */
  hint?: boolean;
  /** How many image-level edges a hint stands for. */
  count?: number;
}

export type LookNode = Node<LookNodeData, 'look'>;
export type EntryNode = Node<EntryNodeData, 'entry'>;
export type PendingNode = Node<PendingNodeData, 'pending'>;
export type GraphNode = LookNode | EntryNode | PendingNode;
export type RelationEdge = Edge<RelationEdgeData, 'relation'>;

export interface BuiltGraph {
  nodes: GraphNode[];
  edges: RelationEdge[];
  /** Look-to-look pairs the layout ranks by (relation + folded hints). */
  rankPairs: Array<[string, string]>;
}

export function buildGraph(
  graph: AssetGraph,
  options: {
    expanded: ReadonlySet<string>;
    selection: GraphSelection;
    onToggle: (variantId: string) => void;
  },
): BuiltGraph {
  const kind: CardKind = graph.card_kind;
  const { expanded, selection } = options;
  const variants = graph.variants ?? [];
  const lookOfEntry = new Map<string, string>();
  for (const variant of variants) {
    for (const entry of variant.entries ?? []) lookOfEntry.set(entry.id, variant.id);
  }
  const pendingByLook = new Map<string, AssetGraphPendingJob[]>();
  for (const job of graph.pending ?? []) {
    const look =
      job.target_variant_id ??
      (job.source_entry_id ? lookOfEntry.get(job.source_entry_id) : undefined) ??
      variants.find((v) => v.is_default)?.id;
    if (!look) continue;
    pendingByLook.set(look, [...(pendingByLook.get(look) ?? []), job]);
  }

  const nodes: GraphNode[] = [];
  for (const variant of variants) {
    const isExpanded = expanded.has(variant.id);
    const pending = pendingByLook.get(variant.id) ?? [];
    const size = lookSize(variant, kind, isExpanded, isExpanded ? pending.length : 0);
    nodes.push({
      id: variantNodeId(variant.id),
      type: 'look',
      position: { x: 0, y: 0 },
      width: size.width,
      height: size.height,
      selected: selection.type === 'variant' && selection.id === variant.id,
      data: {
        variant,
        kind,
        rows: attributeRows(variant, kind),
        expanded: isExpanded,
        anchorEntryId: graph.anchor_entry_id ?? null,
        pendingCount: pending.length,
        width: size.width,
        height: size.height,
        onToggle: options.onToggle,
      },
    });
    if (!isExpanded) continue;
    const children: Array<AssetEntry | AssetGraphPendingJob> = [
      ...(variant.entries ?? []),
      ...pending,
    ];
    children.forEach((child, index) => {
      const position = childPosition(variant, kind, index);
      if ('job_id' in child) {
        nodes.push({
          id: pendingNodeId(child.job_id),
          type: 'pending',
          parentId: variantNodeId(variant.id),
          extent: 'parent',
          draggable: false,
          selectable: false,
          position,
          width: ENTRY_WIDTH,
          height: ENTRY_HEIGHT,
          data: { job: child },
        });
        return;
      }
      nodes.push({
        id: entryNodeId(child.id),
        type: 'entry',
        parentId: variantNodeId(variant.id),
        extent: 'parent',
        draggable: false,
        position,
        width: ENTRY_WIDTH,
        height: ENTRY_HEIGHT,
        selected: selection.type === 'entry' && selection.id === child.id,
        data: { entry: child, isAnchor: child.id === graph.anchor_entry_id },
      });
    });
  }

  const edges: RelationEdge[] = [];
  const rankPairs: Array<[string, string]> = [];
  const hints = new Map<string, RelationEdge>();
  for (const edge of graph.edges ?? []) {
    const data: RelationEdgeData = {
      relations: edge.relations,
      label: edge.label,
      origin: edge.origin,
    };
    const selected = selection.type === 'edge' && selection.id === edge.id;
    if (edge.level === 'variant') {
      edges.push(
        relationEdge(
          edge,
          variantNodeId(edge.source_id),
          variantNodeId(edge.target_id),
          data,
          selected,
        ),
      );
      rankPairs.push([edge.source_id, edge.target_id]);
      continue;
    }
    if (edge.level !== 'entry') continue;
    const sourceLook = lookOfEntry.get(edge.source_id);
    const targetLook = lookOfEntry.get(edge.target_id);
    if (!sourceLook || !targetLook) continue;
    if (expanded.has(sourceLook) && expanded.has(targetLook)) {
      edges.push(
        relationEdge(
          edge,
          entryNodeId(edge.source_id),
          entryNodeId(edge.target_id),
          data,
          selected,
        ),
      );
      continue;
    }
    if (sourceLook === targetLook) continue;
    rankPairs.push([sourceLook, targetLook]);
    const key = `${sourceLook}>${targetLook}`;
    const existing = hints.get(key);
    if (existing?.data) {
      existing.data.count = (existing.data.count ?? 1) + 1;
      existing.data.relations = [...new Set([...existing.data.relations, ...edge.relations])];
      continue;
    }
    hints.set(key, {
      id: `hint:${key}`,
      type: 'relation',
      source: variantNodeId(sourceLook),
      target: variantNodeId(targetLook),
      selectable: false,
      focusable: false,
      data: { relations: [...edge.relations], hint: true, count: 1 },
    });
  }
  edges.push(...hints.values());
  return { nodes, edges, rankPairs };
}

function relationEdge(
  edge: AssetEdge,
  source: string,
  target: string,
  data: RelationEdgeData,
  selected: boolean,
): RelationEdge {
  return {
    id: edge.id,
    type: 'relation',
    source,
    target,
    selected,
    data,
    // Image-level edges draw above the look boxes they cross.
    zIndex: edge.level === 'entry' ? 10 : 0,
  };
}

/**
 * Looks in derivation order (sources first; ties keep the API's own order,
 * default look first) with each look's first parent — what the narrow-screen
 * outline indents by. Relation edges only; the graph is a DAG per level.
 */
export function outlineOrder(
  graph: AssetGraph,
): Array<{ variant: AssetVariant; depth: number; parents: string[] }> {
  const variants = graph.variants ?? [];
  const order = variants.map((v) => v.id);
  const parents = new Map<string, string[]>(order.map((id) => [id, []]));
  for (const edge of graph.edges ?? []) {
    if (edge.level !== 'variant') continue;
    parents.get(edge.target_id)?.push(edge.source_id);
  }
  const depth = new Map<string, number>();
  const visit = (id: string, trail: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (trail.has(id)) return 0;
    trail.add(id);
    const ups = parents.get(id) ?? [];
    const value = ups.length ? Math.max(...ups.map((up) => visit(up, trail))) + 1 : 0;
    trail.delete(id);
    depth.set(id, value);
    return value;
  };
  for (const id of order) visit(id, new Set());
  const byId = new Map(variants.map((v) => [v.id, v]));
  return [...order]
    .sort(
      (a, b) => (depth.get(a) ?? 0) - (depth.get(b) ?? 0) || order.indexOf(a) - order.indexOf(b),
    )
    .map((id) => ({
      variant: byId.get(id)!,
      depth: depth.get(id) ?? 0,
      parents: parents.get(id) ?? [],
    }));
}
