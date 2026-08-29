import type { Draft } from '@/lib/api/types';

/**
 * Where a "生成的视频" card should go. Same destinations the rest of the
 * product already uses: a published work's own page, or the job page that
 * a script breakpoint's "查看视频" already lands on. `/publish/{draftId}`
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
  if (draft?.latest_job_id) return `/jobs/${draft.latest_job_id}`;
  return undefined;
}
