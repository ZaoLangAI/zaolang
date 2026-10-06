/**
 * Session identity for `/create/new`. The pathname never changes across
 * script jump-outs, draft resumes, or video-job notification clicks — only
 * the query does — so `CreateStudio` must remount on this key or it keeps
 * the previous session's `draftId` / `activeJobId` / `pendingDraft` ref.
 *
 * A notification href is `?mode=video_creation&draftId=&jobId=` (see
 * `videoCreationStudioHref`). Draft cards omit `jobId` and resume
 * `latest_job_id`. Images are no longer made here (AC-8): they resume in
 * their card workspace (`asset-job-href.ts`).
 */
export function studioSessionKey(input: {
  draftId?: string | null;
  jobId?: string | null;
  mode: string;
  videoAssetKind?: string;
  targetCharacterId?: string;
  subjectNameHint?: string;
  /** The script studio's "建议切分" chip key — without this, clicking from
   * one unbound breakpoint's chip straight to another (both `draftId`-less
   * "fresh" sessions) would not remount `CreateStudio`, leaving the first
   * breakpoint's typed-over prompt/continuity state bleeding into the
   * second's. */
  linkBreakpointKey?: string;
  /** The previous breakpoint's video, if any — see
   * `VideoGenerationStudio`'s `continuitySourceAssetId`. Included for the
   * same reason as `linkBreakpointKey` above: two different breakpoints can
   * otherwise share an identical "fresh" key. */
  continuitySourceAssetId?: string;
  /** Plaza "用此设定创作" `?skillId=` — two different recipes must not
   * share a fresh session key. */
  skillId?: string;
}): string {
  if (input.draftId) {
    return input.jobId ? `draft:${input.draftId}|job:${input.jobId}` : `draft:${input.draftId}`;
  }
  return [
    'fresh',
    input.mode,
    input.videoAssetKind,
    input.targetCharacterId,
    input.subjectNameHint,
    input.linkBreakpointKey,
    input.continuitySourceAssetId,
    input.skillId,
  ]
    .filter((part) => Boolean(part))
    .join('|');
}
