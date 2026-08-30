import { api } from '@/lib/api/client';
import { ApiError, isApiError } from '@/lib/api/errors';
import { streamPost } from '@/lib/sse-post';
import type { Asset, AuthorSummary, Page, ShortformProfiles } from '@/lib/api/types';

import type { CanonicalDocument, EditCommand } from './engine/ports';

export interface DramaSeries {
  id: string;
  title: string;
  description: string | null;
  kind: string;
  default_locale: string;
  status: string;
  allow_external_models: boolean;
  shortform_profile_key: string | null;
  english_title: string | null;
  planned_episode_count: number | null;
  genre_tags: string[];
  target_platforms: string[];
  logo_asset_id: string | null;
  logo_url: string | null;
  episode_count: number;
  script_count: number;
  video_count: number;
  published_count: number;
  created_at: string;
  updated_at: string;
  owner: AuthorSummary;
  /** "owner" for the caller's own series, "collaborator" when viewing a
   * series someone else invited them into (see `back/app/domain/editor
   * /collaborators.py`). Drives which management actions render — trash,
   * publish, platform-connect and analytics stay owner-only regardless of
   * `is_collaboration`. */
  viewer_role: 'owner' | 'collaborator';
  /** True once the series has at least one *active* collaborator — shown
   * to the owner too, so they can tell which of their own series are
   * shared. */
  is_collaboration: boolean;
  collaborator_count: number;
}

export interface SeriesCollaborator {
  id: string;
  user_id: string;
  handle: string;
  display_name: string;
  avatar_url: string | null;
  status: 'pending' | 'active' | 'declined' | 'removed';
  invited_by_user_id: string;
  created_at: string;
  responded_at: string | null;
}

export interface CollaborationInvite {
  id: string;
  series_id: string;
  series_title: string;
  series_logo_url: string | null;
  inviter: AuthorSummary;
  created_at: string;
}

export interface DramaSeriesCreateInput {
  title: string;
  description?: string;
  english_title?: string;
  planned_episode_count?: number;
  genre_tags?: string[];
  target_platforms: string[];
  logo_asset_id?: string | null;
}

export type DramaSeriesUpdateInput = Partial<{
  title: string;
  description: string;
  english_title: string;
  planned_episode_count: number;
  genre_tags: string[];
  target_platforms: string[];
  logo_asset_id: string | null;
}>;

export interface DramaSeriesListParams {
  q?: string;
  genre?: string;
  sort?: 'updated_at' | 'created_at';
  sort_dir?: 'asc' | 'desc';
  status?: 'trashed';
  [key: string]: string | undefined;
}

export interface DramaEpisode {
  id: string;
  series_id: string;
  season_number: number;
  episode_number: number;
  episode_kind: string;
  title: string;
  synopsis: string | null;
  status: string;
  canonical_work_id: string | null;
  /** Whether this episode has at least one script-writing turn — `false`
   * flags a script shell whose first draft is still streaming elsewhere or
   * failed outright (see `back/app/domain/script_writing/service.py`'s
   * `list_scripts`, which is turn-agnostic for the same reason). */
  has_script_turns: boolean;
}

export interface EpisodeContentLink {
  id: string;
  episode_id: string;
  content_type: string;
  content_ref_id: string;
  role: string;
  created_at: string;
}

export interface CutRevision {
  id: string;
  cut_id: string;
  revision_no: number;
  parent_revision_id: string | null;
  duration_ticks: number;
  content_hash: string;
  document: CanonicalDocument;
  /** asset_id -> short-lived playable URL, for every asset referenced by this revision. */
  asset_urls: Record<string, string>;
  created_at: string;
}

export interface EpisodeCut {
  id: string;
  episode_id: string;
  kind: string;
  name: string;
  status: string;
  head_revision_id: string | null;
  source_asset_id: string | null;
  source_job_id: string | null;
  source_url: string | null;
  lease_held: boolean;
  head: CutRevision | null;
}

export interface CutRevisionSummary {
  id: string;
  cut_id: string;
  revision_no: number;
  parent_revision_id: string | null;
  duration_ticks: number;
  is_head: boolean;
  created_at: string;
}

export interface EpisodeExport {
  id: string;
  status: string;
  profile_key: string;
  width: number;
  height: number;
  format: string;
  output_asset_id: string | null;
  output_url: string | null;
  created_at: string;
  bound_draft_id: string | null;
  published_work_id: string | null;
  is_canonical: boolean;
}

export interface EditorLease {
  id: string;
  cut_id: string;
  expires_at: string;
  token?: string | null;
  base_revision_id: string | null;
}

export interface EditPlan {
  id: string;
  cut_id: string;
  base_revision_id: string;
  status: string;
  summary: string | null;
  commands: EditCommand[];
  diff: Record<string, unknown>;
  warnings: unknown[];
  applied_revision_id: string | null;
}

export interface DeliveryVariant {
  id: string;
  cut_revision_id: string;
  profile_key: string;
  width: number;
  height: number;
  format: string;
  spec_hash: string;
  status: string;
}

export interface EditorExport {
  id: string;
  variant_id: string;
  status: string;
  operation_key: string;
  attempt: number;
  progress: number;
  output_asset_id: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

export function listDramaSeries(params?: DramaSeriesListParams) {
  return api.get<DramaSeries[]>('/v1/drama-series', { query: params });
}

let editorAvailableCache: Promise<boolean> | null = null;

/**
 * Cheap, session-cached "is the drama editor turned on" probe, used so
 * entry points elsewhere (e.g. the job page's Enter editor button) don't
 * have to render an always-on button that 404s when the flag is off.
 * Any non-404 outcome (including a network blip) fails open so a transient
 * error never hides a feature that is actually enabled.
 */
export function checkEditorAvailable(): Promise<boolean> {
  editorAvailableCache ??= listDramaSeries()
    .then(() => true)
    .catch((error: unknown) => {
      editorAvailableCache = null;
      return !(isApiError(error) && error.isNotFound);
    });
  return editorAvailableCache;
}

export function createDramaSeries(input: DramaSeriesCreateInput) {
  return api.post<DramaSeries>('/v1/drama-series', input, {
    idempotencyKey: crypto.randomUUID(),
  });
}

export function getDramaSeries(seriesId: string) {
  return api.get<DramaSeries>(`/v1/drama-series/${seriesId}`);
}

export function updateDramaSeries(seriesId: string, input: DramaSeriesUpdateInput) {
  return api.patch<DramaSeries>(`/v1/drama-series/${seriesId}`, input);
}

export function trashDramaSeries(seriesId: string) {
  return api.delete<void>(`/v1/drama-series/${seriesId}`);
}

export function untrashDramaSeries(seriesId: string) {
  return api.post<DramaSeries>(`/v1/drama-series/${seriesId}/untrash`);
}

export function purgeDramaSeries(seriesId: string) {
  return api.delete<void>(`/v1/drama-series/${seriesId}/purge`);
}

export function listCollaborators(seriesId: string) {
  return api.get<SeriesCollaborator[]>(`/v1/drama-series/${seriesId}/collaborators`);
}

export function inviteCollaborator(seriesId: string, identifier: string) {
  return api.post<SeriesCollaborator>(`/v1/drama-series/${seriesId}/collaborators`, { identifier });
}

export function removeCollaborator(seriesId: string, collaboratorId: string) {
  return api.delete<void>(`/v1/drama-series/${seriesId}/collaborators/${collaboratorId}`);
}

export function listMyCollaborationInvites() {
  return api.get<CollaborationInvite[]>('/v1/collaboration-invites');
}

export function acceptCollaborationInvite(collaboratorId: string) {
  return api.post<SeriesCollaborator>(`/v1/collaboration-invites/${collaboratorId}/accept`);
}

export function declineCollaborationInvite(collaboratorId: string) {
  return api.post<SeriesCollaborator>(`/v1/collaboration-invites/${collaboratorId}/decline`);
}

export function listEpisodes(seriesId: string) {
  return api.get<DramaEpisode[]>(`/v1/drama-series/${seriesId}/episodes`);
}

export function createEpisode(
  seriesId: string,
  input: {
    title: string;
    episode_number?: number;
    season_number?: number;
    episode_kind?: string;
    synopsis?: string;
  },
) {
  return api.post<DramaEpisode>(`/v1/drama-series/${seriesId}/episodes`, input, {
    idempotencyKey: crypto.randomUUID(),
  });
}

export function getEpisode(episodeId: string) {
  return api.get<DramaEpisode>(`/v1/drama-episodes/${episodeId}`);
}

export function updateEpisode(
  episodeId: string,
  input: Partial<{
    title: string;
    synopsis: string;
    episode_kind: string;
    season_number: number;
    episode_number: number;
    status: string;
  }>,
) {
  return api.patch<DramaEpisode>(`/v1/drama-episodes/${episodeId}`, input);
}

export function deleteEpisode(episodeId: string) {
  return api.delete<void>(`/v1/drama-episodes/${episodeId}`);
}

export function createContentLink(
  episodeId: string,
  input: { content_type: string; content_ref_id: string; role?: string },
) {
  return api.post<EpisodeContentLink>(`/v1/drama-episodes/${episodeId}/content-links`, input, {
    idempotencyKey: crypto.randomUUID(),
  });
}

export function listContentLinks(episodeId: string) {
  return api.get<EpisodeContentLink[]>(`/v1/drama-episodes/${episodeId}/content-links`);
}

export function deleteContentLink(episodeId: string, linkId: string) {
  return api.delete<void>(`/v1/drama-episodes/${episodeId}/content-links/${linkId}`);
}

export function setCanonicalWork(episodeId: string, workId: string | null) {
  return api.post<DramaEpisode>(`/v1/drama-episodes/${episodeId}/set-canonical-work`, {
    work_id: workId,
  });
}

export function listEpisodeCuts(episodeId: string) {
  return api.get<EpisodeCut[]>(`/v1/drama-episodes/${episodeId}/cuts`);
}

export function createCutFromAsset(
  episodeId: string,
  input: { asset_id: string; name?: string; kind?: string; job_id?: string },
) {
  return api.post<EpisodeCut>(`/v1/drama-episodes/${episodeId}/cuts`, input, {
    idempotencyKey: crypto.randomUUID(),
  });
}

export function getCut(cutId: string) {
  return api.get<EpisodeCut>(`/v1/episode-cuts/${cutId}`);
}

export function listCutRevisions(cutId: string) {
  return api.get<CutRevisionSummary[]>(`/v1/episode-cuts/${cutId}/revisions`);
}

export function restoreRevision(
  cutId: string,
  input: {
    revisionId: string;
    expectedRevisionId: string | null;
    leaseId: string;
    leaseToken: string;
  },
) {
  return api.post<CutRevision>(`/v1/episode-cuts/${cutId}/revisions:restore`, {
    revision_id: input.revisionId,
    expected_revision_id: input.expectedRevisionId,
    lease_id: input.leaseId,
    lease_token: input.leaseToken,
  });
}

export function listEpisodeExports(episodeId: string) {
  return api.get<EpisodeExport[]>(`/v1/drama-episodes/${episodeId}/exports`);
}

export { createCutFromJob } from './from-job';

export function acquireLease(cutId: string, browserInstanceId: string) {
  return api.post<EditorLease>(`/v1/episode-cuts/${cutId}/leases`, {
    browser_instance_id: browserInstanceId,
  });
}

export function heartbeatLease(
  cutId: string,
  leaseId: string,
  token: string,
  browserInstanceId: string,
) {
  return api.post<EditorLease>(
    `/v1/episode-cuts/${cutId}/leases/${leaseId}/heartbeat`,
    { browser_instance_id: browserInstanceId },
    { headers: { 'x-editor-lease-token': token } },
  );
}

export function releaseLease(
  cutId: string,
  leaseId: string,
  token: string,
  options?: { keepalive?: boolean },
) {
  return api.delete<void>(`/v1/episode-cuts/${cutId}/leases/${leaseId}`, {
    headers: { 'x-editor-lease-token': token },
    keepalive: options?.keepalive,
  });
}

export function applyCommands(
  cutId: string,
  input: {
    batchId: string;
    expectedRevisionId: string | null;
    leaseId: string;
    leaseToken: string;
    commands: EditCommand[];
  },
) {
  return api.post<CutRevision>(`/v1/episode-cuts/${cutId}/revisions`, {
    schema_version: 1,
    batch_id: input.batchId,
    expected_revision_id: input.expectedRevisionId,
    lease_id: input.leaseId,
    lease_token: input.leaseToken,
    commands: input.commands,
  });
}

export async function createEditPlan(
  cutId: string,
  goal: string,
  options?: { onThinking?: (delta: string) => void; signal?: AbortSignal },
): Promise<EditPlan> {
  let plan: EditPlan | null = null;
  for await (const frame of streamPost(
    `/v1/episode-cuts/${cutId}/edit-plans`,
    { goal },
    options?.signal,
  )) {
    if (frame.event === 'thinking' && typeof frame.data.text === 'string') {
      options?.onThinking?.(frame.data.text);
    } else if (frame.event === 'complete') {
      plan = frame.data as unknown as EditPlan;
    } else if (frame.event === 'error') {
      const message = typeof frame.data.message === 'string' ? frame.data.message : 'plan failed';
      throw new ApiError(502, { error: { code: 'AGENT_STREAM_ERROR', message } }, message);
    }
  }
  if (!plan) {
    throw new ApiError(
      502,
      { error: { code: 'AGENT_STREAM_ERROR', message: 'empty plan' } },
      'empty plan',
    );
  }
  return plan;
}

export function applyEditPlan(
  planId: string,
  leaseId: string,
  leaseToken: string,
  selectedIndexes?: number[],
) {
  return api.post<CutRevision>(`/v1/edit-plans/${planId}/apply`, {
    lease_id: leaseId,
    lease_token: leaseToken,
    selected_indexes: selectedIndexes,
  });
}

export function rejectEditPlan(planId: string) {
  return api.post<EditPlan>(`/v1/edit-plans/${planId}/reject`);
}

export function batchCreateVariants(revisionId: string, profileKeys: string[]) {
  return api.post<DeliveryVariant[]>(
    `/v1/cut-revisions/${revisionId}/delivery-variants:batchCreate`,
    {
      profile_keys: profileKeys,
      format: 'mp4',
      caption_mode: 'burned',
    },
  );
}

export function queueExports(variantIds: string[]) {
  return api.post<EditorExport[]>('/v1/editor-exports', {
    variant_ids: variantIds,
    operation_key: crypto.randomUUID(),
  });
}

export function claimExport(runnerInstanceId: string) {
  return api.post<EditorExport>('/v1/editor-exports:claim', {
    runner_instance_id: runnerInstanceId,
    chrome_or_edge: true,
    webcodecs: typeof VideoEncoder !== 'undefined',
    webgpu: false,
  });
}

export function heartbeatExport(exportId: string, progress: number, stage: string) {
  return api.post<EditorExport>(`/v1/editor-exports/${exportId}/heartbeat`, { progress, stage });
}

export function completeExport(exportId: string, uploadSessionId: string) {
  return api.post<EditorExport>(`/v1/editor-exports/${exportId}/complete`, {
    upload_session_id: uploadSessionId,
  });
}

export function failExport(exportId: string, code: string, message: string) {
  return api.post<EditorExport>(`/v1/editor-exports/${exportId}/fail`, { code, message });
}

export function cancelExport(exportId: string) {
  return api.post<EditorExport>(`/v1/editor-exports/${exportId}/cancel`);
}

export function bindEditorExport(draftId: string, exportId: string) {
  return api.post<{ draft_id: string; export_id: string }>(
    `/v1/drafts/${draftId}/bind-editor-export`,
    {
      export_id: exportId,
      confirmed: true,
    },
  );
}

export function loadShortformProfiles() {
  return api.get<ShortformProfiles>('/v1/shortform/profiles');
}

export function presignExportUpload(
  exportId: string,
  payload: { filename: string; mime_type: string; size_bytes: number; checksum_sha256: string },
) {
  return api.post<{
    upload_session_id: string;
    upload_url: string;
    object_key: string;
    expires_at: string;
    required_headers: Record<string, string>;
  }>(`/v1/editor-exports/${exportId}/upload-session`, payload);
}

export function listMyMedia() {
  return api.get<Page<Asset>>('/v1/assets:mine');
}

/**
 * The backend models `EditorOperationResponse.result` as an open `dict[str,
 * Any]` (it's a poll-once-for-several-kinds-of-job envelope: export /
 * edit-plan / media-analysis all share the shape). This narrows `result` to
 * the one shape the media library's transcript flow actually reads, instead
 * of re-exporting the untyped generated schema.
 */
export interface EditorOperation {
  id: string;
  kind: string;
  status: string;
  progress: number;
  result?: {
    transcript?: {
      language?: string | null;
      segments?: Array<{ start_ms: number; end_ms: number; text: string }>;
    };
    [key: string]: unknown;
  };
  error?: { code?: string; [key: string]: unknown } | null;
}

export function requestTranscription(assetId: string) {
  return api.post<EditorOperation>(`/v1/media-assets/${assetId}/transcriptions`);
}

export function getOperation(operationId: string) {
  return api.get<EditorOperation>(`/v1/editor-operations/${operationId}`);
}
