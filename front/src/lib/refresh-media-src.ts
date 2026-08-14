import { api } from '@/lib/api/client';
import type { Asset, Draft, GenerationJob, WorkDetail } from '@/lib/api/types';

export async function refreshAssetUrl(assetId: string): Promise<string | null> {
  const asset = await api.get<Asset>(`/v1/assets/${assetId}`);
  return asset.url ?? null;
}

export async function refreshJobOutputUrl(jobId: string): Promise<string | null> {
  const job = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
  if (job.output_asset_id) {
    try {
      return await refreshAssetUrl(job.output_asset_id);
    } catch {
      return job.output_url ?? null;
    }
  }
  return job.output_url ?? null;
}

export async function refreshWorkMediaUrl(workId: string): Promise<string | null> {
  const work = await api.get<WorkDetail>(`/v1/works/${workId}`);
  return work.current_version?.media_url ?? null;
}

export async function refreshDraftOutputUrl(draftId: string): Promise<string | null> {
  const draft = await api.get<Draft>(`/v1/drafts/${draftId}`);
  if (draft.output_asset_id) {
    try {
      return await refreshAssetUrl(draft.output_asset_id);
    } catch {
      return draft.output_url ?? null;
    }
  }
  return draft.output_url ?? null;
}
