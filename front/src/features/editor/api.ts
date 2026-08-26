import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { ShortformProfiles } from '@/lib/api/types';

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
  created_at: string;
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

export function listDramaSeries() {
  return api.get<DramaSeries[]>('/v1/drama-series');
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

export function createDramaSeries(title: string) {
  return api.post<DramaSeries>(
    '/v1/drama-series',
    { title },
    { idempotencyKey: crypto.randomUUID() },
  );
}

export function getDramaSeries(seriesId: string) {
  return api.get<DramaSeries>(`/v1/drama-series/${seriesId}`);
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

export function getCut(cutId: string) {
  return api.get<EpisodeCut>(`/v1/episode-cuts/${cutId}`);
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

export function createEditPlan(cutId: string, goal: string) {
  return api.post<EditPlan>(`/v1/episode-cuts/${cutId}/edit-plans`, { goal });
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
