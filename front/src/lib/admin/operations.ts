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

/**
 * The two modality axes a `kind="media"` endpoint is configured along, mirroring
 * `MEDIA_INPUT_MODALITIES`/`MEDIA_OUTPUT_MODALITIES` in
 * `app/platform_config/schemas.py`. `audio` is a valid input (e.g. voice-driven
 * lip-sync video) even though no capability derives from it alone yet.
 */
export const MEDIA_INPUT_MODALITIES = ['text', 'image', 'video', 'audio'] as const;
export type MediaInputModality = (typeof MEDIA_INPUT_MODALITIES)[number];
export const MEDIA_OUTPUT_MODALITIES = ['image', 'video', 'audio'] as const;
export type MediaOutputModality = (typeof MEDIA_OUTPUT_MODALITIES)[number];

export const MODALITY_LABEL_KEYS: Record<MediaInputModality | MediaOutputModality, string> = {
  text: 'modalityText',
  image: 'modalityImage',
  video: 'modalityVideo',
  audio: 'modalityAudio',
};

/** One (input, output) pair per operation — mirrors the backend's
 * `_CAPABILITY_MODALITY_MAP`. Kept in sync by hand since this is a small,
 * stable, six-entry table. */
const OPERATION_MODALITY_MAP: Record<
  OperationValue,
  readonly [MediaInputModality, MediaOutputModality]
> = {
  text_to_image: ['text', 'image'],
  image_to_image: ['image', 'image'],
  text_to_video: ['text', 'video'],
  image_to_video: ['image', 'video'],
  video_to_video: ['video', 'video'],
  audio_generation: ['text', 'audio'],
};

/**
 * Which operations a modality selection covers — the client-side mirror of
 * `capabilities_for_modalities`, so the console shows the same capability set
 * the API derives on save, and the creative agent's candidate picker can list
 * an endpoint's routable capabilities without a second round trip.
 */
export function capabilitiesForModalities(
  inputModalities: readonly string[],
  outputModalities: readonly string[],
): OperationValue[] {
  const inputs = new Set(inputModalities);
  const outputs = new Set(outputModalities);
  return OPERATIONS.filter((operation) => {
    const [input, output] = OPERATION_MODALITY_MAP[operation];
    return inputs.has(input) && outputs.has(output);
  });
}
