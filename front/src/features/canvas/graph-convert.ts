import type { Edge, Node } from '@xyflow/react';

import { breakpointKey } from '@/features/script/script-breakpoint';

import type {
  CanvasEdge,
  CanvasGraph,
  CanvasNode,
  CanvasNodeBinding,
  CanvasNodeKind,
  CanvasNodeOrigin,
  CanvasSnapshot,
} from './api';

/** What a rendered node knows about itself.
 *
 * `stale` is the load-bearing field: the domain side has no stable ids for
 * scenes or shots (a scene is keyed by its heading string, a shot by
 * `{heading}#{ordinal}` — see `script-breakpoint.ts`), so any script revision
 * that renames or reorders scenes can orphan a binding. When that happens the
 * node stays on the canvas, marked stale, instead of vanishing and taking the
 * user's layout with it.
 */
export interface CanvasNodeData extends Record<string, unknown> {
  kind: CanvasNodeKind;
  label: string;
  subtitle?: string;
  thumbnailUrl?: string | null;
  binding?: CanvasNodeBinding;
  stale: boolean;
  payload?: Record<string, unknown>;
  /** Carried through the React Flow round trip, not rendered.
   *
   * `revision` is the card's compare-and-set token. Every commit goes
   * `graphToFlow` -> user edits -> `flowToGraph`, so dropping it here would
   * make each update look like it came from a client that had never seen the
   * server's row, and every one of them would come back a conflict.
   */
  revision?: number;
  origin?: CanvasNodeOrigin;
}

export type CanvasFlowNode = Node<CanvasNodeData>;
export type CanvasFlowEdge = Edge;

let idCounter = 0;

/** Client-minted, stable for the node's whole life. Prefixed like the
 * backend's own ids so a canvas node id is never mistaken for a domain id. */
export function newCanvasNodeId(): string {
  idCounter += 1;
  return `cnd_${Date.now().toString(36)}${idCounter.toString(36)}`;
}

export function newCanvasEdgeId(): string {
  idCounter += 1;
  return `cne_${Date.now().toString(36)}${idCounter.toString(36)}`;
}

interface ResolveIndex {
  episodeIds: Set<string>;
  skillIds: Set<string>;
  draftIds: Set<string>;
  workIds: Set<string>;
  /** `${episodeId}::${breakpointKey}` for every shot the scripts still name. */
  shotKeys: Set<string>;
  /** Assets the server resolved for this caller — see `_node_asset_urls`. */
  assetIds: Set<string>;
}

function buildIndex(snapshot: CanvasSnapshot): ResolveIndex {
  const index: ResolveIndex = {
    episodeIds: new Set(),
    skillIds: new Set(),
    draftIds: new Set(),
    workIds: new Set(),
    shotKeys: new Set(),
    assetIds: new Set(Object.keys(snapshot.assets ?? {})),
  };
  for (const episode of snapshot.episodes) {
    index.episodeIds.add(episode.id);
    for (const key of shotKeysOf(episode.script)) {
      index.shotKeys.add(`${episode.id}::${key}`);
    }
  }
  for (const skill of snapshot.skills) index.skillIds.add(skill.id);
  for (const link of snapshot.content_links) {
    if (link.content_type === 'draft') index.draftIds.add(link.content_ref_id);
    if (link.content_type === 'work') index.workIds.add(link.content_ref_id);
  }
  return index;
}

/** Every breakpoint key a script document currently contains.
 *
 * Mirrors `script-breakpoint.ts`'s own ordinal rule (count of preceding
 * `breakpoint` blocks within the same scene) rather than re-deriving a
 * second, subtly different numbering.
 */
export function shotKeysOf(script: Record<string, unknown> | null): string[] {
  if (!script) return [];
  const scenes = script.scenes;
  if (!Array.isArray(scenes)) return [];
  const keys: string[] = [];
  for (const scene of scenes) {
    if (typeof scene !== 'object' || scene === null) continue;
    const heading = (scene as { heading?: unknown }).heading;
    const blocks = (scene as { blocks?: unknown }).blocks;
    if (typeof heading !== 'string' || !Array.isArray(blocks)) continue;
    let ordinal = 0;
    for (const block of blocks) {
      if (typeof block !== 'object' || block === null) continue;
      if ((block as { type?: unknown }).type !== 'breakpoint') continue;
      keys.push(breakpointKey(heading, ordinal));
      ordinal += 1;
    }
  }
  return keys;
}

function isBindingLive(binding: CanvasNodeBinding | undefined, index: ResolveIndex): boolean {
  // A node with no binding (a note, a loose image) can never go stale.
  if (!binding) return true;
  switch (binding.kind) {
    case 'series':
      return true;
    case 'episode':
      return !!binding.episode_id && index.episodeIds.has(binding.episode_id);
    case 'shot':
      return (
        !!binding.episode_id &&
        !!binding.breakpoint_key &&
        index.shotKeys.has(`${binding.episode_id}::${binding.breakpoint_key}`)
      );
    case 'skill':
      return !!binding.skill_id && index.skillIds.has(binding.skill_id);
    case 'clip':
      if (binding.draft_id) return index.draftIds.has(binding.draft_id);
      if (binding.work_id) return index.workIds.has(binding.work_id);
      return false;
    case 'image':
    case 'video':
      // An unbound picture card is a placeholder, which is fine. One bound to
      // an asset hydration did not return is genuinely broken — deleted, or
      // never the caller's to read.
      return !binding.asset_id || index.assetIds.has(binding.asset_id);
    default:
      return true;
  }
}

function labelFor(
  node: CanvasNode,
  snapshot: CanvasSnapshot,
): { label: string; subtitle?: string; thumbnailUrl?: string | null } {
  const binding = node.binding;
  const stored = typeof node.data?.label === 'string' ? (node.data.label as string) : '';
  switch (binding?.kind) {
    case 'series':
      return { label: snapshot.series?.title ?? stored };
    case 'episode': {
      const episode = snapshot.episodes.find((e) => e.id === binding.episode_id);
      if (!episode) break;
      return {
        label: episode.title,
        subtitle: `S${episode.season_number}E${episode.episode_number}`,
      };
    }
    case 'skill': {
      const skill = snapshot.skills.find((s) => s.id === binding.skill_id);
      if (!skill) break;
      return { label: skill.title, subtitle: skill.category, thumbnailUrl: skill.thumbnail_url };
    }
    case 'clip': {
      const link = snapshot.content_links.find(
        (l) => l.content_ref_id === (binding.draft_id ?? binding.work_id),
      );
      if (!link) break;
      return {
        label: link.title ?? stored,
        subtitle: link.role,
        thumbnailUrl: link.thumbnail_url,
      };
    }
    case 'shot':
      return { label: stored || (binding.breakpoint_key ?? ''), subtitle: binding.breakpoint_key };
    case 'image':
    case 'video': {
      // The URL is resolved per request (see `CanvasSnapshotAsset`), so an
      // uploaded picture renders from hydration rather than from anything
      // stored on the node.
      if (!binding.asset_id) break;
      const asset = snapshot.assets?.[binding.asset_id];
      if (!asset) break;
      return { label: stored, thumbnailUrl: asset.url };
    }
    default:
      break;
  }
  // Falls through for unbound cards and for bindings whose target is gone —
  // the stored label is the last thing we knew, which is more useful on a
  // stale card than an empty box.
  return { label: stored };
}

/** Stored graph -> what `<ReactFlow>` renders. */
export function graphToFlow(
  graph: CanvasGraph,
  snapshot: CanvasSnapshot,
): { nodes: CanvasFlowNode[]; edges: CanvasFlowEdge[] } {
  const index = buildIndex(snapshot);
  const nodes: CanvasFlowNode[] = (graph.nodes ?? []).map((node, i) => {
    const { label, subtitle, thumbnailUrl } = labelFor(node, snapshot);
    return {
      id: node.id,
      type: 'canvasNode',
      position: node.position ?? { x: i * 260, y: 0 },
      // Restore the stored size. `flowToGraph` has always written it back
      // from `measured`, but nothing read it in again — so a card the server
      // inserted (an Agent result) had no dimensions at all and rendered at
      // its image's natural size, filling the viewport.
      ...(node.size ? { width: node.size.width, height: node.size.height } : {}),
      data: {
        kind: node.kind,
        label,
        subtitle,
        thumbnailUrl,
        // Normalised to `undefined`: the wire uses `null` for "no binding"
        // (JSON has no undefined), while `CanvasNodeData` — and every reader
        // of it — treats an absent binding as absent, not as an empty value.
        binding: node.binding ?? undefined,
        stale: !isBindingLive(node.binding ?? undefined, index),
        payload: node.data,
        revision: node.revision,
        origin: node.origin,
      },
    };
  });

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges: CanvasFlowEdge[] = (graph.edges ?? [])
    // A stored edge whose endpoints were removed would make React Flow warn
    // on every render; drop it here rather than shipping a broken graph in.
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: { kind: edge.kind },
    }));

  return { nodes, edges };
}

/** What `<ReactFlow>` holds -> the graph we persist.
 *
 * Only structure and position are written back: labels and thumbnails are
 * re-derived from the snapshot on every load, so persisting them would just
 * create a second copy that goes stale. The one exception is the label of an
 * unbound card, which has no other home.
 */
export function flowToGraph(nodes: CanvasFlowNode[], edges: CanvasFlowEdge[]): CanvasGraph {
  return {
    nodes: nodes.map<CanvasNode>((node) => ({
      id: node.id,
      kind: node.data.kind,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      // `measured`, not `width`/`height`: in xyflow v12 the latter are the
      // *author-specified* dimensions, which these nodes never set, so
      // reading them persisted nothing at all.
      ...(node.measured?.width && node.measured?.height
        ? { size: { width: node.measured.width, height: node.measured.height } }
        : {}),
      ...(node.data.binding ? { binding: node.data.binding } : {}),
      data: { ...(node.data.payload ?? {}), label: node.data.label },
      // Passed straight back out. `revision` is what `diffGraph` compares
      // against; `origin` only drives a badge but would otherwise be reset to
      // "user" on the first drag of an agent-produced card.
      revision: node.data.revision,
      origin: node.data.origin,
    })),
    edges: edges.map<CanvasEdge>((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      kind: (edge.data as { kind?: string } | undefined)?.kind ?? 'link',
    })),
  };
}

/** Nodes for every domain object the snapshot knows about that the stored
 * graph has no node for yet — how a drama canvas picks up an episode created
 * elsewhere (script studio, dashboard) without the user re-adding it. */
export function missingDomainNodes(graph: CanvasGraph, snapshot: CanvasSnapshot): CanvasNode[] {
  const bound = new Set(
    (graph.nodes ?? [])
      .map((node) => bindingIdentity(node.binding ?? undefined))
      .filter((key): key is string => key !== null),
  );
  const added: CanvasNode[] = [];
  let row = 0;

  // A canvas has at most one series node, so its identity is positional
  // ("the series this canvas is bound to"), not keyed by series id.
  if (snapshot.series && !bound.has('series:self')) {
    added.push({
      id: newCanvasNodeId(),
      kind: 'series',
      position: { x: 0, y: 0 },
      binding: { kind: 'series' },
      data: { label: snapshot.series.title },
    });
  }

  for (const episode of snapshot.episodes) {
    if (bound.has(`episode:${episode.id}`)) continue;
    row += 1;
    added.push({
      id: newCanvasNodeId(),
      kind: 'episode',
      position: { x: 320, y: row * 160 },
      binding: { kind: 'episode', episode_id: episode.id },
      data: { label: episode.title },
    });
  }

  // Clips produced elsewhere show up on their own. This is what closes the
  // generation loop without the studio needing to know the canvas exists: a
  // node's "生成" hands off to `/create/new` carrying `linkEpisodeId`, the
  // draft is linked to that episode server-side, and the next time the canvas
  // loads the hydration snapshot contains it.
  let clipRow = 0;
  for (const link of snapshot.content_links) {
    if (link.content_type !== 'draft' && link.content_type !== 'work') continue;
    const key =
      link.content_type === 'draft'
        ? `draft:${link.content_ref_id}`
        : `work:${link.content_ref_id}`;
    if (bound.has(key)) continue;
    clipRow += 1;
    added.push({
      id: newCanvasNodeId(),
      kind: 'clip',
      position: { x: 660, y: clipRow * 200 },
      binding:
        link.content_type === 'draft'
          ? { kind: 'clip', episode_id: link.episode_id, draft_id: link.content_ref_id }
          : { kind: 'clip', episode_id: link.episode_id, work_id: link.content_ref_id },
      data: { label: link.title ?? '' },
    });
  }

  return added;
}

function bindingIdentity(binding: CanvasNodeBinding | undefined): string | null {
  if (!binding) return null;
  switch (binding.kind) {
    case 'series':
      return 'series:self';
    case 'episode':
      return binding.episode_id ? `episode:${binding.episode_id}` : null;
    case 'shot':
      return binding.episode_id && binding.breakpoint_key
        ? `shot:${binding.episode_id}::${binding.breakpoint_key}`
        : null;
    case 'skill':
      return binding.skill_id ? `skill:${binding.skill_id}` : null;
    case 'clip':
      return binding.draft_id
        ? `draft:${binding.draft_id}`
        : binding.work_id
          ? `work:${binding.work_id}`
          : null;
    default:
      return null;
  }
}

/**
 * Asset ids of the picture cards wired *into* a node.
 *
 * This is what makes an edge mean something rather than being decoration: an
 * image card connected to a prompt card is that generation's reference image.
 * Only direct upstream neighbours count — a transitive walk would quietly
 * attach the whole left-hand side of the board to one request.
 */
export function upstreamAssetIds(nodeId: string, graph: CanvasGraph): string[] {
  const byId = new Map((graph.nodes ?? []).map((node) => [node.id, node] as const));
  const ids: string[] = [];
  for (const edge of graph.edges ?? []) {
    if (edge.target !== nodeId) continue;
    const source = byId.get(edge.source);
    const assetId = source?.binding?.asset_id;
    if (typeof assetId === 'string' && assetId && !ids.includes(assetId)) ids.push(assetId);
  }
  return ids;
}
