'use client';

import { useSession } from '@/components/auth/session-provider';
import type { GenerationModelOption, Operation } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

/** The one operation set `GenerationParams.forced_model` accepts (see
 * `back/app/api/schemas/jobs.py`'s `validate_generation_params`) — the
 * picker must not offer this for an operation that would reject it. */
const FORCED_MODEL_OPERATIONS: readonly Operation[] = [
  'text_to_image',
  'image_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
];

/**
 * The "指定模型" picker's live model list for one operation.
 *
 * Sourced from `GET /v1/generation-jobs/models`, itself a live read of the
 * exact same enabled-endpoint catalogue `route_score` filters against — an
 * operator adding/disabling a model at `/admin/models` is reflected here on
 * the next fetch, never a hardcoded list. Returns an empty list (no
 * request) while signed out or for an operation outside the image/video/
 * audio creation scope.
 */
export function useGenerationModels(operation: Operation): GenerationModelOption[] {
  const { status: sessionStatus } = useSession();
  const eligible = FORCED_MODEL_OPERATIONS.includes(operation);
  const { data } = useResource<{ models: GenerationModelOption[] }>(
    sessionStatus === 'authenticated' && eligible
      ? `/v1/generation-jobs/models?operation=${operation}`
      : null,
  );
  return data?.models ?? [];
}

/** Last-resort roster shown before the live catalogue above has loaded
 * (signed-out visitor, or the request still in flight) — mirrors
 * `AUDIO_VOICES`'s old fixed set in `app/api/schemas/jobs.py`, kept only as
 * a placeholder so a voice `Select` is never empty, never validated
 * against. Shared by every surface that lets a user pick a TTS voice
 * without picking a specific model first (`AudioGenerationStudio`, the
 * script batch dubbing dialog). */
export const FALLBACK_VOICES = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'] as const;

/** The union of every model's own voice roster, in first-seen order — shown
 * when no specific model is picked ("自动选择") so the picker still offers
 * real voice ids instead of forcing a model pick just to see one. */
export function unionVoices(modelOptions: GenerationModelOption[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const option of modelOptions) {
    for (const voiceId of option.voices ?? []) {
      if (!seen.has(voiceId)) {
        seen.add(voiceId);
        ordered.push(voiceId);
      }
    }
  }
  return ordered;
}
