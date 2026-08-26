/**
 * Image-creation drafts (`text_to_image` / `image_to_image`) resume straight
 * into the studio's inline flow (progress + version history — see
 * `ImageGenerationStudio`) rather than a standalone page. Shared by
 * `library-tabs.tsx` (resuming a draft) and `notification-format.ts`
 * (routing a job notification) so both agree on which operations qualify.
 */
export const IMAGE_CREATION_OPERATIONS = new Set(['text_to_image', 'image_to_image']);

export function isImageCreationOperation(operation: unknown): boolean {
  return typeof operation === 'string' && IMAGE_CREATION_OPERATIONS.has(operation);
}

export function imageCreationStudioHref(draftId: string): string {
  return `/create/new?mode=image_creation&draftId=${draftId}`;
}
