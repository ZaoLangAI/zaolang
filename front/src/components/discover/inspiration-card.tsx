'use client';

import { useLocale, useTranslations } from 'next-intl';

import { tileRatio } from '@/components/discover/inspiration-aspect';
import { Poster } from '@/components/media/poster';
import { Badge } from '@/components/ui/primitives';
import { IconHeart, IconTombstone } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';
import { useRevealOnView } from '@/lib/use-reveal';

/**
 * Tile for the inspiration wall.
 *
 * Deliberately not `WorkCard`: that one is a link straight to the work page,
 * while a tile here opens the preview dialog. Keeping them apart means the
 * profile and library grids do not inherit a modal they have no use for.
 *
 * The poster takes its shape from the cover's own pixels rather than a fixed
 * frame: that is what gives the wall its staggered columns, and it means a
 * vertical work is not cropped to a landscape box to fit the grid.
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

  return (
    <article ref={revealRef} className="group flex flex-col gap-2">
      <button
        type="button"
        onClick={() => onOpen(work)}
        aria-label={tDiscover('openPreview', { title: work.title })}
        className="block w-full rounded-[var(--radius-md)] text-left focus-visible:outline-2"
      >
        <Poster
          src={work.cover_url}
          alt={work.title}
          ratio={tileRatio(work.cover_width, work.cover_height)}
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
        </Poster>
      </button>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{work.title}</p>
        <div className="mt-0.5 flex items-center justify-between gap-3 text-xs text-muted">
          <span className="truncate">{work.author.display_name}</span>
          <span className="tabular flex shrink-0 items-center gap-1">
            <IconHeart className="size-3.5" />
            {formatCount(work.stats.like_count, locale)}
          </span>
        </div>
      </div>
    </article>
  );
}
