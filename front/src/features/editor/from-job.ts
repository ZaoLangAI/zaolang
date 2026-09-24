import { api } from '@/lib/api/client';
import type { EpisodeCut } from '@/lib/api/types';

/** Thin entry from a finished video job into an EpisodeCut. Kept off the editor barrel. */
export function createCutFromJob(jobId: string, seriesId?: string) {
  return api.post<EpisodeCut>('/v1/episode-cuts:from-job', { job_id: jobId, series_id: seriesId });
}
