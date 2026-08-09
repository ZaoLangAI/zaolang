/**
 * The six `Operation` values, and where their labels live.
 *
 * Shared by every console surface that has to name an operation — the
 * workflow editor's tabs, the agent variant capability chips, the provider
 * capability matrix — so they cannot drift apart. The labels themselves are
 * the `adminProviders` capability strings, which already had all six.
 */
export const OPERATIONS = [
  'text_to_image',
  'image_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
] as const;

export type OperationValue = (typeof OPERATIONS)[number];

export const OPERATION_LABEL_KEYS: Record<OperationValue, string> = {
  text_to_image: 'capabilityTextToImage',
  image_to_image: 'capabilityImageToImage',
  text_to_video: 'capabilityTextToVideo',
  image_to_video: 'capabilityImageToVideo',
  video_to_video: 'capabilityVideoToVideo',
  audio_generation: 'capabilityAudioGeneration',
};

/** Falls back to the raw value so an operation added to the backend enum
 * before the front end knows about it still renders as something. */
export function operationLabelKey(operation: string): string | null {
  return OPERATION_LABEL_KEYS[operation as OperationValue] ?? null;
}
