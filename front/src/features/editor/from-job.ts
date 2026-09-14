import { api } from '@/lib/api/client';
import type { EpisodeCut } from '@/lib/api/types';

/** Thin entry from a finished video job into an EpisodeCut. Kept off the editor barrel. */
export function createCutFromJob(jobId: string, seriesId?: string) {
  return api.post<EpisodeCut>('/v1/episode-cuts:from-job', { job_id: jobId, series_id: seriesId });
}

export interface CutAssembleResult {
  cut: EpisodeCut;
  /** Breakpoints (`{heading}#{n}`) and dialogue lines (`{heading}#L{n}`) left
   * out; `reason` is `no_output`, `unknown_duration` or `not_owned`. */
  skipped: { key: string; reason: string }[];
}

/** Script → rough cut: lays the episode's generated segment videos, voice
 * lines and dialogue captions onto its 粗剪 cut in script order. */
export function assembleCutFromScript(
  episodeId: string,
  options: { orderedKeys?: string[]; includeAudio?: boolean } = {},
) {
  return api.post<CutAssembleResult>('/v1/episode-cuts:assemble', {
    episode_id: episodeId,
    ordered_keys: options.orderedKeys,
    include_audio: options.includeAudio ?? true,
  });
}
