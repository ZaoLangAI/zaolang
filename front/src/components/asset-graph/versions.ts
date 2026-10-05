import type { AssetEntry, AssetGraph } from '@/lib/api/types';

/**
 * Versions of one image never show in the graph as separate nodes: an
 * image, its 调整修改 outputs (joined by `edit` edges) and the candidates
 * competing for the same slot (`asset_variants.service.slot_mates`: a
 * look's sheet / each view / each expression set / a scene's master; the
 * identity portrait card-wide) fold into one image node. The node shows the
 * group's head — the anchor, else an approved version, else the newest —
 * and the inspector lists every version.
 */

const SLOT_TYPES = new Set([
  'identity_portrait',
  'character_sheet',
  'view',
  'expression_sheet',
  'master',
]);

function slotKey(entry: AssetEntry, variantId: string): string | null {
  if (!SLOT_TYPES.has(entry.entry_type)) return null;
  const scope = entry.entry_type === 'identity_portrait' ? '*' : variantId;
  const view = entry.entry_type === 'view' ? (entry.view ?? '') : '';
  const expressions =
    entry.entry_type === 'expression_sheet' ? [...(entry.expressions ?? [])].sort().join(',') : '';
  return `${scope}|${entry.entry_type}|${view}|${expressions}`;
}

export interface VersionIndex {
  /** Every entry id → its group's head id. */
  headOf: Map<string, string>;
  /** Head id → the group's entries, head first, then newest first. */
  versions: Map<string, AssetEntry[]>;
}

export function versionIndex(graph: AssetGraph): VersionIndex {
  const parent = new Map<string, string>();
  const find = (id: string): string => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root)!;
    parent.set(id, root);
    return root;
  };
  const union = (a: string, b: string) => {
    if (!parent.has(a) || !parent.has(b)) return;
    parent.set(find(a), find(b));
  };
  const byId = new Map<string, AssetEntry>();
  const order = new Map<string, number>();
  const slots = new Map<string, string>();
  for (const variant of graph.variants ?? []) {
    for (const entry of variant.entries ?? []) {
      parent.set(entry.id, entry.id);
      byId.set(entry.id, entry);
      order.set(entry.id, order.size);
      const key = slotKey(entry, variant.id);
      if (!key) continue;
      const first = slots.get(key);
      if (first) union(entry.id, first);
      else slots.set(key, entry.id);
    }
  }
  for (const edge of graph.edges ?? []) {
    if (edge.level === 'entry' && edge.relations.includes('edit')) {
      union(edge.source_id, edge.target_id);
    }
  }
  const groups = new Map<string, AssetEntry[]>();
  for (const id of byId.keys()) {
    const root = find(id);
    groups.set(root, [...(groups.get(root) ?? []), byId.get(id)!]);
  }
  const newest = (a: AssetEntry, b: AssetEntry) =>
    (b.created_at ?? '').localeCompare(a.created_at ?? '') ||
    (order.get(b.id) ?? 0) - (order.get(a.id) ?? 0);
  const headOf = new Map<string, string>();
  const versions = new Map<string, AssetEntry[]>();
  for (const members of groups.values()) {
    const sorted = [...members].sort(newest);
    const head =
      sorted.find((e) => e.id === graph.anchor_entry_id) ??
      [...members].find((e) => e.status !== 'candidate') ??
      sorted[0]!;
    versions.set(head.id, [head, ...sorted.filter((e) => e.id !== head.id)]);
    for (const member of members) headOf.set(member.id, head.id);
  }
  return { headOf, versions };
}
