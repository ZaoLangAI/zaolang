/**
 * Video-creation drafts (`text_to_video` / `image_to_video` / `video_to_video`)
 * — the video-side equivalent of `image-draft.ts`. `videoCreationStudioHref`
 * now reopens the same draft's full version history/latest output, exactly
 * like an image draft (see `VideoGenerationStudio`'s `initialDraft`/
 * `draftId`) — video creation is no longer a "material only" resume. Shared
 * by `recent-draft-card.tsx` (resuming a draft, `draftId` only) and
 * `notification-format.ts` (routing a job notification, `draftId` +
 * `jobId`), same split as `image-draft.ts`.
 */
export const VIDEO_CREATION_OPERATIONS = new Set([
  'text_to_video',
  'image_to_video',
  'video_to_video',
]);

export function isVideoCreationOperation(operation: unknown): boolean {
  return typeof operation === 'string' && VIDEO_CREATION_OPERATIONS.has(operation);
}

export function videoCreationStudioHref(draftId: string, jobId?: string): string {
  const params = new URLSearchParams({ mode: 'video_creation', draftId });
  if (jobId) params.set('jobId', jobId);
  return `/create/new?${params.toString()}`;
}
