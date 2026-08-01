import { useLocale, useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { Badge } from '@/components/ui/primitives';
import { IconHeart, IconTombstone } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';

/**
 * The card used by discover, profile and library.
 *
 * Provenance is not optional even at card size: the design requires source,
 * licence and AI marking to survive down to mobile, so the author line and the
 * remixable badge stay on every breakpoint.
 */
export function WorkCard({
  work,
  badge,
  priority,
  className,
}: {
  work: WorkSummary;
  /** Extra state label, e.g. draft or private in the library. */
  badge?: { label: string; tone?: 'neutral' | 'primary' | 'amber' | 'success' };
  priority?: boolean;
  className?: string;
}) {
  const t = useTranslations('work');
  const locale = useLocale() as Locale;
  const tombstoned = work.lifecycle_status === 'tombstone';

  return (
    <article className={cn('group flex flex-col gap-2.5', className)}>
      <Link
        href={`/work/${work.id}`}
        className="block rounded-[var(--radius-md)] focus-visible:outline-2"
      >
        <Poster
          src={work.cover_url}
          alt={work.title}
          priority={priority}
          className={cn(
            'transition-transform duration-300 group-hover:scale-[1.01]',
            tombstoned && 'opacity-60 grayscale',
          )}
        >
          {badge ? (
            <span className="absolute right-2 top-2">
              <Badge tone={badge.tone ?? 'neutral'}>{badge.label}</Badge>
            </span>
          ) : null}
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
      </Link>

      <div className="min-w-0">
        <Link href={`/work/${work.id}`} className="block truncate text-sm font-medium">
          {work.title}
        </Link>
        <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted">
          <Link
            href={`/profile/${work.author.handle}`}
            className="truncate hover:text-text"
            title={work.author.display_name}
          >
            {work.author.display_name}
          </Link>
          <span className="tabular flex shrink-0 items-center gap-1">
            <IconHeart className="size-3.5" />
            {formatCount(work.stats.like_count, locale)}
          </span>
        </div>
      </div>
    </article>
  );
}
