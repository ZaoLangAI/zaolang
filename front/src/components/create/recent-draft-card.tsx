'use client';

import { DraftPoster } from '@/components/media/draft-poster';
import { IconButton } from '@/components/ui/button';
import { IconPencil, IconUpload } from '@/components/ui/icons';
import { Link, useRouter } from '@/i18n/navigation';
import type { Draft } from '@/lib/api/types';
import { draftDisplayTitle } from '@/lib/draft-title';
import { assetWorkspaceHref, isImageOperation } from '@/lib/asset-job-href';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';

/**
 * One "最近草稿" card. Split out from `RecentDrafts` (a server component)
 * because an asset-image or video draft needs client-side hover state for
 * its 编辑/发布 shortcut icons (编辑 = the card's workspace / the video
 * studio) — every other draft renders exactly as before.
 */
export function RecentDraftCard({
  draft,
  fallbackTitle,
  editLabel,
  publishLabel,
}: {
  draft: Draft;
  fallbackTitle: string;
  editLabel: string;
  publishLabel: string;
}) {
  const operation = draft.params?.operation;
  // A general image draft (the retired image studio) has nowhere to edit.
  const imageWorkspace = isImageOperation(operation)
    ? assetWorkspaceHref(draft.params ?? {})
    : null;
  // Only meaningful once there is an output to build the next edit on — a
  // still-generating or failed video draft has nothing to hand the studio.
  const isVideoDraft = isVideoCreationOperation(operation) && Boolean(draft.output_asset_id);
  const editHref = imageWorkspace
    ? imageWorkspace
    : isVideoDraft
      ? videoCreationStudioHref(draft.id)
      : null;
  const router = useRouter();
  const label = draftDisplayTitle(draft, fallbackTitle);

  return (
    <Link href={`/publish/${draft.id}`} className="group block">
      <DraftPoster draft={draft} alt={label} className="border border-border">
        {editHref ? (
          <div className="absolute inset-0 flex items-center justify-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <IconButton
              label={editLabel}
              variant="secondary"
              size="sm"
              className="border-border bg-surface/90"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                router.push(editHref);
              }}
            >
              <IconPencil className="size-4" />
            </IconButton>
            <IconButton
              label={publishLabel}
              variant="secondary"
              size="sm"
              className="border-border bg-surface/90"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                router.push(`/publish/${draft.id}`);
              }}
            >
              <IconUpload className="size-4" />
            </IconButton>
          </div>
        ) : null}
      </DraftPoster>
      <p className="mt-2 truncate text-xs">{label}</p>
    </Link>
  );
}
