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
  'video_analysis',
] as const;

export type OperationValue = (typeof OPERATIONS)[number];

export const OPERATION_LABEL_KEYS: Record<OperationValue, string> = {
  text_to_image: 'capabilityTextToImage',
  image_to_image: 'capabilityImageToImage',
  text_to_video: 'capabilityTextToVideo',
  image_to_video: 'capabilityImageToVideo',
  video_to_video: 'capabilityVideoToVideo',
  audio_generation: 'capabilityAudioGeneration',
  video_analysis: 'capabilityVideoAnalysis',
};

/** Falls back to the raw value so an operation added to the backend enum
 * before the front end knows about it still renders as something. */
export function operationLabelKey(operation: string): string | null {
  return OPERATION_LABEL_KEYS[operation as OperationValue] ?? null;
}

/**
 * `ImageAssetKind` — the extra "what is this image *for*" dimension layered
 * on top of `text_to_image`/`image_to_image` (mirrors the backend enum in
 * `app/models/enums.py`). `general` is the default/legacy behaviour and is
 * represented as `null` everywhere a workflow template or job param is
 * addressed, matching `GenerationWorkflowTemplate.asset_kind` being nullable.
 */
export const IMAGE_ASSET_KINDS = ['character', 'scene', 'cover'] as const;
export type ImageAssetKindValue = (typeof IMAGE_ASSET_KINDS)[number];

export const IMAGE_ASSET_KIND_LABEL_KEYS: Record<ImageAssetKindValue, string> = {
  character: 'assetKindCharacter',
  scene: 'assetKindScene',
  cover: 'assetKindCover',
};

/** Only `text_to_image`/`image_to_image` have a meaningful asset-kind split
 * — every other operation always runs the one generic workflow. */
export function operationHasAssetKinds(operation: OperationValue): boolean {
  return operation === 'text_to_image' || operation === 'image_to_image';
}

/**
 * Tabs for the workflow *editor* specifically: `text_to_image` and
 * `image_to_image` resolve to exactly one `GenerationWorkflowTemplate`
 * (backend `canonical_operation`) and are mandatory-prompt/optional-reference
 * variants of the same graph, so the editor shows a single merged "图片创作"
 * tab under the `text_to_image` key instead of two. Everywhere else that uses
 * `OPERATIONS` keeps them distinct — the provider capability matrix and agent
 * variant chips still need to say a provider/agent supports pure generation
 * without supporting editing, or vice versa. Kept as its own literal tuple
 * (rather than `OPERATIONS.filter(...)`) so indexing it stays a plain
 * `OperationValue`, not `OperationValue | undefined`. */
export const WORKFLOW_EDITOR_OPERATIONS = [
  'text_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
] as const satisfies readonly OperationValue[];

/**
 * The two modality axes a `kind="media"` endpoint is configured along, mirroring
 * `MEDIA_INPUT_MODALITIES`/`MEDIA_OUTPUT_MODALITIES` in
 * `app/platform_config/schemas.py`. `audio` is a valid input (e.g. voice-driven
 * lip-sync video) even though no capability derives from it alone yet.
 */
export const MEDIA_INPUT_MODALITIES = ['text', 'image', 'video', 'audio'] as const;
export type MediaInputModality = (typeof MEDIA_INPUT_MODALITIES)[number];
// `text` joined the output side for `video_analysis` — the first capability
// that reads media and writes a structured text breakdown instead of
// generating more media. Mirrors `MEDIA_OUTPUT_MODALITIES` in
// `app/platform_config/schemas.py`.
export const MEDIA_OUTPUT_MODALITIES = ['image', 'video', 'audio', 'text'] as const;
export type MediaOutputModality = (typeof MEDIA_OUTPUT_MODALITIES)[number];

/** `kind="general"` endpoints declare input types from this smaller set —
 * `text` is always on, `image` is a declarative label only, `video` makes
 * the endpoint a `video_analysis` candidate. Mirrors `GENERAL_INPUT_
 * MODALITIES` in `app/platform_config/schemas.py`. */
export const GENERAL_INPUT_MODALITIES = ['text', 'image', 'video'] as const;
export type GeneralInputModality = (typeof GENERAL_INPUT_MODALITIES)[number];

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
  video_analysis: ['video', 'text'],
};

/**
 * Which operations a modality selection covers — the client-side mirror of
 * `capabilities_for_modalities`, so the console shows the same capability set
 * the API derives on save.
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

/** HTTP contract names for `kind="media"` endpoints. Mirrors
 * `MEDIA_PROTOCOLS` in `app/platform_config/schemas.py`. Display names are
 * the standard, not the gateway vendor — AiHubMix image/audio is OpenAI. */
export const MEDIA_PROTOCOLS = [
  'openai',
  'minimax',
  'comfyui',
  'google',
  'dashscope',
  'ark',
  'kling',
] as const;
export type MediaProtocol = (typeof MEDIA_PROTOCOLS)[number];

export const IMPLEMENTED_MEDIA_PROTOCOLS: ReadonlySet<MediaProtocol> = new Set([
  'openai',
  'minimax',
  'dashscope',
]);

export const PROTOCOL_LABEL_KEYS: Record<MediaProtocol, string> = {
  openai: 'protocolOpenAI',
  minimax: 'protocolMiniMax',
  comfyui: 'protocolComfyUI',
  google: 'protocolGoogle',
  dashscope: 'protocolDashScope',
  ark: 'protocolArk',
  kling: 'protocolKling',
};

const PROTOCOL_OPERATIONS: Record<MediaProtocol, readonly OperationValue[]> = {
  // Video joined via the OpenAI Videos API track — see backend
  // `_OPENAI_CAPABILITIES` (`app/platform_config/schemas.py`). Not every
  // openai-protocol video model accepts a reference (e.g. `wan2.7-
  // videoedit`'s openai-shaped endpoint has no `input_reference` field);
  // that is enforced by the provider adapter, not this modality gate.
  openai: [
    'text_to_image',
    'image_to_image',
    'audio_generation',
    'text_to_video',
    'image_to_video',
    'video_to_video',
  ],
  minimax: ['text_to_video', 'image_to_video', 'video_to_video'],
  comfyui: ['text_to_image', 'image_to_image', 'text_to_video', 'image_to_video', 'video_to_video'],
  google: [],
  dashscope: ['video_analysis'],
  ark: [],
  kling: [],
};

/** Drop modality ticks that the newly selected protocol cannot serve. */
export function constrainModalities(
  protocol: MediaProtocol,
  inputModalities: readonly MediaInputModality[],
  outputModalities: readonly MediaOutputModality[],
): { input_modalities: MediaInputModality[]; output_modalities: MediaOutputModality[] } {
  const allowed = new Set(PROTOCOL_OPERATIONS[protocol] ?? []);
  const pairs = OPERATIONS.filter((operation) => allowed.has(operation)).map(
    (operation) => OPERATION_MODALITY_MAP[operation],
  );
  const allowedInputs = new Set(pairs.map(([input]) => input));
  const allowedOutputs = new Set(pairs.map(([, output]) => output));
  return {
    input_modalities: inputModalities.filter((item) => allowedInputs.has(item)),
    output_modalities: outputModalities.filter((item) => allowedOutputs.has(item)),
  };
}
