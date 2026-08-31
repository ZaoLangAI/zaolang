/**
 * Session identity for `/create/new`. The pathname never changes across
 * script jump-outs, draft resumes, or image-job notification clicks — only
 * the query does — so `CreateStudio` must remount on this key or it keeps
 * the previous character's `draftId` / `activeJobId` / `pendingDraft` ref.
 *
 * A notification href is `?mode=image_creation&draftId=&jobId=` (see
 * `imageCreationStudioHref`). Draft cards omit `jobId` and resume
 * `latest_job_id`. The script jump-out's `returnTo` trio is written onto
 * `Draft.params` at first submit and restored here when the URL does not
 * carry it.
 */

const LINK_KINDS = ['character', 'scene'] as const;
type LinkKind = (typeof LINK_KINDS)[number];

export function sanitizeReturnTo(raw: string | undefined): string | undefined {
  if (!raw || !raw.startsWith('/create/script/')) return undefined;
  return raw;
}

export function studioSessionKey(input: {
  draftId?: string | null;
  jobId?: string | null;
  mode: string;
  assetKind?: string;
  videoAssetKind?: string;
  targetCharacterId?: string;
  targetSceneId?: string;
  subjectNameHint?: string;
}): string {
  if (input.draftId) {
    return input.jobId ? `draft:${input.draftId}|job:${input.jobId}` : `draft:${input.draftId}`;
  }
  return [
    'fresh',
    input.mode,
    input.assetKind,
    input.videoAssetKind,
    input.targetCharacterId,
    input.targetSceneId,
    input.subjectNameHint,
  ]
    .filter((part) => Boolean(part))
    .join('|');
}

export function readDraftReturnContext(params: unknown): {
  returnTo?: string;
  returnLinkKind?: LinkKind;
  returnLinkLabel?: string;
} {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return {};
  const record = params as Record<string, unknown>;
  const returnTo =
    typeof record.return_to === 'string' ? sanitizeReturnTo(record.return_to) : undefined;
  const kind = record.return_link_kind;
  const returnLinkKind = LINK_KINDS.includes(kind as LinkKind) ? (kind as LinkKind) : undefined;
  const label =
    typeof record.return_link_label === 'string'
      ? record.return_link_label.trim().slice(0, 60)
      : '';
  return {
    returnTo,
    returnLinkKind,
    returnLinkLabel: label || undefined,
  };
}

/** Written onto a new draft so a later `?draftId=` resume can rebuild the
 * script-studio jump-back without the original query string. */
export function draftReturnParams(input: {
  returnTo?: string;
  returnLinkKind?: LinkKind;
  returnLinkLabel?: string;
}): Record<string, string> | undefined {
  const returnTo = sanitizeReturnTo(input.returnTo);
  if (!returnTo) return undefined;
  return {
    return_to: returnTo,
    ...(input.returnLinkKind ? { return_link_kind: input.returnLinkKind } : {}),
    ...(input.returnLinkLabel ? { return_link_label: input.returnLinkLabel } : {}),
  };
}
