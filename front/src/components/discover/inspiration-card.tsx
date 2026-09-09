'use client';

import { useLocale, useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { Avatar } from '@/components/work/avatar';
import { Badge } from '@/components/ui/primitives';
import { IconHeart, IconTombstone } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { WorkSummary } from '@/lib/api/types';
import { cn, controlPress } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import { useRevealOnView } from '@/lib/use-reveal';

/**
 * Tile for the inspiration wall.
 *
 * Deliberately not `WorkCard`: that one is a link straight to the work page,
 * while a tile here opens the preview dialog. Keeping them apart means the
 * profile and library grids do not inherit a modal they have no use for.
 *
 * The poster is a fixed 16:9 frame so a five-column grid stays even; a
 * vertical cover is cropped rather than stretching the row.
 */
export function InspirationCard({
  work,
  onOpen,
  priority,
}: {
  work: WorkSummary;
  onOpen: (work: WorkSummary) => void;
  priority?: boolean;
}) {
  const t = useTranslations('work');
  const tDiscover = useTranslations('discover');
  const locale = useLocale() as Locale;
  const tombstoned = work.lifecycle_status === 'tombstone';
  const revealRef = useRevealOnView<HTMLElement>();
  const durationSeconds =
    work.media_type === 'video' && work.duration_ms && work.duration_ms > 0
      ? work.duration_ms / 1000
      : null;

  return (
    <article ref={revealRef} className="group flex flex-col gap-2">
      <button
        type="button"
        onClick={() => onOpen(work)}
        aria-label={tDiscover('openPreview', { title: work.title })}
        className={cn(
          'block w-full rounded-[var(--radius-md)] text-left focus-visible:outline-2',
          controlPress,
        )}
      >
        <Poster
          src={work.cover_url}
          alt={work.title}
          mediaType={work.media_type}
          lazy
          priority={priority}
          sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, (max-width: 1280px) 25vw, 20vw"
          className={cn(
            'transition-transform duration-300 group-hover:scale-[1.01]',
            tombstoned && 'opacity-60 grayscale',
          )}
        >
          {tombstoned ? (
            <span className="absolute left-2 top-2">
              <Badge tone="danger" icon={<IconTombstone className="size-3.5" />}>
                {t('tombstoned')}
              </Badge>
            </span>
          ) : work.remixable ? (
            <span className="absolute left-2 top-2">
              <Badge tone="amber">{t('remix')}</Badge>
            </span>
          ) : null}
          {durationSeconds !== null ? (
            <span className="pointer-events-none absolute bottom-2 right-2 z-10 rounded bg-bg/80 px-1.5 py-0.5 text-[10px] tabular text-text">
              {formatDuration(durationSeconds)}
            </span>
          ) : null}
        </Poster>
      </button>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{work.title}</p>
        <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted">
          <span className="flex min-w-0 items-center gap-1.5">
            <Avatar src={work.author.avatar_url} name={work.author.display_name} size="xs" />
            <span className="truncate">{work.author.display_name}</span>
          </span>
          <span className="tabular flex shrink-0 items-center gap-1">
            <IconHeart className="size-3.5" />
            {formatCount(work.stats.like_count, locale)}
          </span>
        </div>
      </div>
    </article>
  );
}
