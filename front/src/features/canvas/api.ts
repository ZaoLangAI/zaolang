import { api } from '@/lib/api/client';

/** Canvas node kinds.
 *
 * Drama-mode kinds bind to a real domain object; sandbox kinds stand alone.
 * Both sets render on the same canvas — a drama canvas may hold plain notes,
 * and a free canvas can gain drama nodes once its content is sent to an
 * episode.
 */
export type CanvasNodeKind =
  // Drama-mode: bound to a domain object via `binding`.
  | 'series'
  | 'episode'
  | 'shot'
  | 'skill'
  | 'clip'
  // Mode-agnostic sandbox cards.
  | 'image'
  | 'video'
  | 'prompt'
  | 'note'
  // The card an Agent run hangs off.
  | 'agent';

/** Who put the card on the canvas. Drives a badge, never a permission. */
export type CanvasNodeOrigin = 'user' | 'agent';

/** What a node points at in the domain.
 *
 * The canvas owns its node ids and records the domain reference separately,
 * because the domain side has no stable ids for scenes or shots — a scene is
 * keyed by its heading string and a shot by `{heading}#{ordinal}`, both of
 * which drift when a script revision renames or reorders scenes. Re-binding
 * is therefore best-effort on load, and a node whose binding no longer
 * resolves is shown as stale rather than dropped.
 */
export interface CanvasNodeBinding {
  kind: CanvasNodeKind;
  episode_id?: string;
  breakpoint_key?: string;
  skill_id?: string;
  draft_id?: string;
  work_id?: string;
  asset_id?: string;
}

export interface CanvasNode {
  id: string;
  kind: CanvasNodeKind;
  position: { x: number; y: number };
  size?: { width: number; height: number } | null;
  z_index?: number;
  binding?: CanvasNodeBinding | null;
  data?: Record<string, unknown>;
  origin?: CanvasNodeOrigin;
  /** Compare-and-set token for this one card.
   *
   * Scoped to the node rather than the document so that a card moving under
   * you costs you that card, not the twenty other edits in the same flush.
   * A card the client just minted and has not yet had acknowledged has no
   * server revision; `0` stands for "not yet persisted".
   */
  revision?: number;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
  kind?: string;
}

export interface CanvasGraph {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface CanvasSnapshotEpisode {
  id: string;
  season_number: number;
  episode_number: number;
  episode_kind: string;
  title: string;
  synopsis: string | null;
  status: string;
  canonical_work_id: string | null;
  /** The full `ScriptDocument`; shots are derived client-side with the same
   * helper the script studio uses, so the two can't disagree. */
  script: Record<string, unknown> | null;
}

export interface CanvasSnapshotContentLink {
  id: string;
  episode_id: string;
  content_type: string;
  content_ref_id: string;
  role: string;
  title: string | null;
  status: string | null;
  output_asset_id: string | null;
  thumbnail_url: string | null;
}

export interface CanvasSnapshotSkill {
  id: string;
  category: string;
  title: string;
  thumbnail_url: string | null;
}

/** Signed URLs for assets the canvas' own image/video cards point at.
 * Resolved per request because a presigned URL expires — storing one in the
 * graph would give a canvas that renders for an hour and breaks after. */
export interface CanvasSnapshotAsset {
  url: string | null;
  media_type: string;
  width: number | null;
  height: number | null;
}

export interface CanvasSnapshot {
  series: {
    id: string;
    title: string;
    english_title: string | null;
    status: string;
    planned_episode_count: number | null;
    genre_tags: string[];
    target_platforms: string[];
    logo_url: string | null;
  } | null;
  episodes: CanvasSnapshotEpisode[];
  content_links: CanvasSnapshotContentLink[];
  skills: CanvasSnapshotSkill[];
  assets: Record<string, CanvasSnapshotAsset>;
}

export type CanvasMode = 'drama' | 'free';
export type CanvasViewerRole = 'owner' | 'collaborator';

export interface CanvasProjectSummary {
  id: string;
  title: string;
  series_id: string | null;
  mode: CanvasMode;
  /** Canvas-scoped sequence cursor. Not a lock — see `graph-ops.ts`. */
  change_seq: number;
  viewer_role: CanvasViewerRole;
  node_count: number;
  created_at: string;
  updated_at: string;
}

export interface CanvasProject extends CanvasProjectSummary {
  viewport: Record<string, unknown>;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  snapshot: CanvasSnapshot;
}

export function listCanvasProjects(): Promise<CanvasProjectSummary[]> {
  return api.get<CanvasProjectSummary[]>('/v1/canvas-projects');
}

export function createCanvasProject(input: {
  title: string;
  seriesId?: string | null;
}): Promise<CanvasProject> {
  return api.post<CanvasProject>('/v1/canvas-projects', {
    title: input.title,
    series_id: input.seriesId ?? null,
  });
}

export function getCanvasProject(canvasId: string): Promise<CanvasProject> {
  return api.get<CanvasProject>(`/v1/canvas-projects/${canvasId}`);
}

/** What a metadata write returns — no graph and no snapshot, because a title
 * or viewport change cannot have altered either. */
export interface CanvasProjectWrite {
  id: string;
  title: string;
  series_id: string | null;
  mode: CanvasMode;
  change_seq: number;
  viewer_role: CanvasViewerRole;
  viewport: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Project metadata only. The graph goes through `applyCanvasGraphOps`. */
export function updateCanvasProject(
  canvasId: string,
  input: { title?: string; viewport?: Record<string, unknown> },
): Promise<CanvasProjectWrite> {
  return api.patch<CanvasProjectWrite>(`/v1/canvas-projects/${canvasId}`, {
    ...(input.title !== undefined ? { title: input.title } : {}),
    ...(input.viewport !== undefined ? { viewport: input.viewport } : {}),
  });
}

export function deleteCanvasProject(canvasId: string): Promise<void> {
  return api.delete<void>(`/v1/canvas-projects/${canvasId}`);
}

/** Resolve-or-create the canvas for a series — one click from series detail. */
export function getSeriesCanvas(seriesId: string): Promise<CanvasProject> {
  return api.get<CanvasProject>(`/v1/drama-series/${seriesId}/canvas`);
}

// --------------------------------------------------------------------------
// Graph writes
// --------------------------------------------------------------------------

export type CanvasOp =
  | { op_id: string; kind: 'node.create'; node: CanvasNode }
  | {
      op_id: string;
      kind: 'node.update';
      node_id: string;
      expected_revision: number;
      position?: { x: number; y: number };
      size?: { width: number; height: number } | null;
      z_index?: number;
      binding?: CanvasNodeBinding | null;
      data?: Record<string, unknown>;
    }
  | { op_id: string; kind: 'node.delete'; node_id: string; expected_revision: number }
  | { op_id: string; kind: 'edge.create'; edge: CanvasEdge }
  | { op_id: string; kind: 'edge.delete'; edge_id: string };

/** One entry in the canvas' append-only change feed.
 *
 * `payload` carries the row as it now stands, so a catching-up client applies
 * the change without a second read. It is empty for a delete: there is nothing
 * left to describe.
 */
export interface CanvasChange {
  seq: number;
  entity_type: 'node' | 'edge' | 'agent_run' | 'agent_task';
  entity_id: string;
  action: 'created' | 'updated' | 'deleted';
  actor: 'user' | 'agent';
  payload: Record<string, unknown>;
}

export interface CanvasOpConflict {
  op_id: string;
  entity_id: string;
  /** `stale_revision` — the card moved under this op. `missing` — it is gone. */
  reason: 'stale_revision' | 'missing';
}

export interface CanvasGraphOpsResult {
  change_seq: number;
  applied: string[];
  conflicts: CanvasOpConflict[];
  changes: CanvasChange[];
  /** The write landed, but the catch-up feed could not be reconstructed from
   * `baseSeq`. Reload to converge — do not read the empty `changes` as
   * "nothing happened", which is also a legitimate outcome. */
  gap: boolean;
}

/**
 * Apply a batch of graph operations.
 *
 * Resolves with 200 even when some ops did not apply: a stale op lands in
 * `conflicts` while the rest of the batch still commits. Callers reconcile the
 * conflicted cards from `changes`, which carries every change after the
 * request's `baseSeq` — including this batch's own writes and anyone else's.
 */
export function applyCanvasGraphOps(
  canvasId: string,
  input: { baseSeq: number; ops: CanvasOp[] },
): Promise<CanvasGraphOpsResult> {
  return api.post<CanvasGraphOpsResult>(`/v1/canvas-projects/${canvasId}/graph-ops`, {
    base_seq: input.baseSeq,
    ops: input.ops,
  });
}

export interface CanvasChangesResult {
  change_seq: number;
  changes: CanvasChange[];
  /** The requested cursor can no longer be reconstructed — reload the canvas
   * rather than treating the empty `changes` as "no news". */
  gap: boolean;
}

export function getCanvasChanges(canvasId: string, since: number): Promise<CanvasChangesResult> {
  return api.get<CanvasChangesResult>(
    `/v1/canvas-projects/${canvasId}/changes?since=${encodeURIComponent(String(since))}`,
  );
}
