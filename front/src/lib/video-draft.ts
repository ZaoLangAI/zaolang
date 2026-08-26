/**
 * Video-creation drafts (`text_to_video` / `image_to_video` / `video_to_video`)
 * — the video-side equivalent of `image-draft.ts`. Unlike an image draft,
 * resuming one never reopens the same draft for iterative refinement; it
 * seeds a *new* `video_to_video` session with the earlier output as
 * material (see `VideoGenerationStudio`'s `initialDraft` prop), because
 * there is no per-draft version history on the video side to iterate
 * within.
 */
export const VIDEO_CREATION_OPERATIONS = new Set([
  'text_to_video',
  'image_to_video',
  'video_to_video',
]);

export function isVideoCreationOperation(operation: unknown): boolean {
  return typeof operation === 'string' && VIDEO_CREATION_OPERATIONS.has(operation);
}

export function videoCreationStudioHref(draftId: string): string {
  return `/create/new?mode=video_creation&draftId=${draftId}`;
}
