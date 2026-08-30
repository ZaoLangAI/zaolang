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

export function resumeEditorHref(cuts: Array<{ id: string }>): string | undefined {
  const cutId = cuts[0]?.id;
  return cutId ? `/studio-editor/${cutId}` : undefined;
}
