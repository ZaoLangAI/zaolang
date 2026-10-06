import { characterManageHref } from '@/lib/characters';
import { propManageHref } from '@/lib/props';
import { sceneManageHref } from '@/lib/scenes';

/**
 * Where an image job, draft or job notification resumes now that images are
 * only generated inside a card workspace (AC-8). An asset image lands in its
 * card's workspace (`/create/{characters,scenes,props}/[id]`, `?look=` the
 * look / variant / condition it targeted); anything else — a general or
 * cover image from the retired image studio, a canvas Agent image — opens
 * its read-only `/jobs/{id}` page, which still offers 去发布 for a draft.
 *
 * Shared by `jobs/[jobId]/page.tsx`, `publish/[draftId]/page.tsx`,
 * `library-tabs.tsx`, `recent-draft-card.tsx` and `notification-format.ts`
 * so all of them agree on which jobs qualify.
 */
export const IMAGE_OPERATIONS = new Set(['text_to_image', 'image_to_image']);

/** The image kinds that still generate: library assets. */
export const ASSET_IMAGE_KINDS = new Set(['character', 'scene', 'prop']);

export function isImageOperation(operation: unknown): boolean {
  return typeof operation === 'string' && IMAGE_OPERATIONS.has(operation);
}

/** An image job the API no longer accepts (general / cover / unset kind):
 * shown read-only — no retry, no promote. */
export function isRetiredImageJob(job: { operation?: unknown; asset_kind?: unknown }): boolean {
  return (
    isImageOperation(job.operation) &&
    !(typeof job.asset_kind === 'string' && ASSET_IMAGE_KINDS.has(job.asset_kind))
  );
}

/** The fields any of a job response, a notification payload or a draft's
 * params may carry. `linked_*` is the card the output filed into (set at
 * write-back); `target_*` is the card the request named. */
export interface AssetJobRef {
  linked_character_id?: unknown;
  linked_scene_id?: unknown;
  linked_prop_id?: unknown;
  target_character_id?: unknown;
  target_scene_id?: unknown;
  target_prop_id?: unknown;
  target_variant_id?: unknown;
}

function id(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/** The card workspace this image belongs to, or `null` when it names none. */
export function assetWorkspaceHref(ref: AssetJobRef): string | null {
  const variant = id(ref.target_variant_id);
  const character = id(ref.linked_character_id) ?? id(ref.target_character_id);
  if (character) return characterManageHref(character, variant);
  const scene = id(ref.linked_scene_id) ?? id(ref.target_scene_id);
  if (scene) return sceneManageHref(scene, variant);
  const prop = id(ref.linked_prop_id) ?? id(ref.target_prop_id);
  if (prop) return propManageHref(prop, variant);
  return null;
}

/** The card workspace, else the job's read-only page. */
export function assetJobHref(jobId: string, ref: AssetJobRef): string {
  return assetWorkspaceHref(ref) ?? `/jobs/${encodeURIComponent(jobId)}`;
}

/** Where an image draft resumes: its card's workspace, else the read-only
 * page of its latest job, else the publish form. */
export function imageDraftHref(draft: {
  id: string;
  latest_job_id?: string | null;
  params?: Record<string, unknown> | null;
}): string {
  const workspace = assetWorkspaceHref(draft.params ?? {});
  if (workspace) return workspace;
  if (draft.latest_job_id) return `/jobs/${encodeURIComponent(draft.latest_job_id)}`;
  return `/publish/${encodeURIComponent(draft.id)}`;
}
