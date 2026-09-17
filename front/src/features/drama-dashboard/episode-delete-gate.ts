/**
 * Workspace delete / resume rules for an episode. The trigger is disabled
 * only when a published output exists — an unpublished cut is not a reason
 * to lock delete (those rows tear down with the episode).
 */
export function isEpisodeDeleteBlocked(input: {
  canonicalWorkId?: string | null;
  exports?: Array<{ published_work_id?: string | null }>;
}): boolean {
  return (
    Boolean(input.canonicalWorkId) ||
    (input.exports ?? []).some((item) => Boolean(item.published_work_id))
  );
}

const DELETABLE_EXPORT_STATUSES = new Set(['succeeded', 'failed', 'cancelled']);

/** A 最终成片 row can be removed only once it is terminal and unpublished. */
export function isExportRecordDeletable(item: {
  status: string;
  published_work_id?: string | null;
}): boolean {
  return !item.published_work_id && DELETABLE_EXPORT_STATUSES.has(item.status);
}

export function resumeEditorHref(
  cuts: Array<{ id: string }>,
  draftId?: string | null,
): string | undefined {
  const cutId = cuts[0]?.id;
  if (!cutId) return undefined;
  const suffix = draftId ? `?draftId=${encodeURIComponent(draftId)}` : '';
  return `/studio-editor/${cutId}${suffix}`;
}
