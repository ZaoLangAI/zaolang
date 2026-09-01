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
];

/**
 * The "指定模型" picker's live model list for one operation.
 *
 * Sourced from `GET /v1/generation-jobs/models`, itself a live read of the
 * exact same enabled-endpoint catalogue `route_score` filters against — an
 * operator adding/disabling a model at `/admin/models` is reflected here on
 * the next fetch, never a hardcoded list. Returns an empty list (no
 * request) while signed out or for an operation outside the image/video
 * creation scope.
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
