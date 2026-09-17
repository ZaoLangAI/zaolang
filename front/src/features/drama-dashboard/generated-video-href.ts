import type { Draft } from '@/lib/api/types';
import { videoCreationStudioHref } from '@/lib/video-draft';

/**
 * The episode "生成的视频" gallery is a result list, not a job tracker.
 * A draft is only a card once it actually produced media (or was
 * published). Failed / cancelled / still-running attempts stay linked
 * for the script chip, but they have no poster to show here.
 */
export function isGeneratedVideoCard({
  contentType,
  draft,
}: {
  contentType: string;
  draft?: Draft;
}): boolean {
  if (contentType === 'work') return true;
  if (contentType !== 'draft') return false;
  return Boolean(draft?.output_asset_id || draft?.output_url || draft?.published_work_id);
}

/**
 * Where a "生成的视频" card should go. Same destinations the rest of the
 * product already uses: a published work's own page, or the video studio
 * that a script breakpoint's "查看/调整视频" already lands on. `/publish/{draftId}`
 * is a form, not a detail, so it is never returned here.
 *
 * A draft with no fetched record (or no job yet) returns undefined so the
 * card stays a poster, not a link to nowhere.
 */
export function generatedVideoDetailHref({
  contentType,
  contentRefId,
  draft,
}: {
  contentType: string;
  contentRefId: string;
  draft?: Draft;
}): string | undefined {
  if (contentType === 'work') return `/work/${contentRefId}`;
  if (contentType !== 'draft') return undefined;
  if (draft?.published_work_id) return `/work/${draft.published_work_id}`;
  if (draft?.latest_job_id) return videoCreationStudioHref(draft.id);
  return undefined;
}
