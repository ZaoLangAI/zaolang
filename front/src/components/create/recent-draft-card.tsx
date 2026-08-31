'use client';

import { useTranslations } from 'next-intl';

import { DraftPoster } from '@/components/media/draft-poster';
import { IconButton } from '@/components/ui/button';
import { IconPencil, IconUpload } from '@/components/ui/icons';
import { Link, useRouter } from '@/i18n/navigation';
import type { Draft } from '@/lib/api/types';
import { imageCreationStudioHref, isImageCreationOperation } from '@/lib/image-draft';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';

/**
 * One "最近草稿" card. Split out from `RecentDrafts` (a server component)
 * because an image- or video-type draft needs client-side hover state for
 * its 编辑/发布 shortcut icons — every other draft renders exactly as before.
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
  const t = useTranslations('createPage');
  const operation = draft.params?.operation;
  const isImageDraft = isImageCreationOperation(operation);
  // Only meaningful once there is an output to build the next edit on — a
  // still-generating or failed video draft has nothing to hand the studio.
  const isVideoDraft = isVideoCreationOperation(operation) && Boolean(draft.output_asset_id);
  const editHref = isImageDraft
    ? imageCreationStudioHref(draft.id)
    : isVideoDraft
      ? videoCreationStudioHref(draft.id)
      : null;
  // A video draft's "编辑" never reopens this exact draft for iterative
  // refinement the way an image draft's does (no per-draft version history
  // on the video side, see `video-draft.ts`) — it seeds a brand-new
  // `video_to_video` job from the earlier output, which reserves credits
  // again. The generic `editLabel` would read as "continue where I left
  // off, free", so a video draft gets its own, more honest tooltip instead.
  const resumeLabel = isVideoDraft ? t('videoResumeLabel') : editLabel;
  const router = useRouter();

  return (
    <Link href={`/publish/${draft.id}`} className="group block">
      <DraftPoster draft={draft} alt={draft.title ?? fallbackTitle} className="border border-border">
        {editHref ? (
          <div className="absolute inset-0 flex items-center justify-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <IconButton
              label={resumeLabel}
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
      <p className="mt-2 truncate text-xs">{draft.title ?? fallbackTitle}</p>
    </Link>
  );
}
