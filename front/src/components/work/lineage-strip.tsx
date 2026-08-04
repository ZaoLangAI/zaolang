'use client';

import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Avatar } from '@/components/work/avatar';
import { IconArrowRight, IconChevronRight, IconTombstone } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { AuthorSummary, LineageAncestor } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

const LineageDialog = dynamic(
  () => import('@/components/lineage/lineage-dialog').then((mod) => mod.LineageDialog),
  { ssr: false },
);

/**
 * The compact lineage row from the design: ancestors as avatars, an arrow
 * between each, and a counter for everything downstream.
 *
 * Withdrawn ancestors still occupy their slot — losing them would make the
 * chain read as if the work came from nowhere.
 */
export function LineageStrip({
  workId,
  ancestors,
  author,
  descendantCount,
}: {
  workId: string;
  ancestors: LineageAncestor[];
  author: AuthorSummary;
  descendantCount: number;
}) {
  const t = useTranslations('work');
  const tPanel = useTranslations('lineagePanel');
  const locale = useLocale() as Locale;
  const [open, setOpen] = useState(false);

  // Oldest first, so the row reads left to right as the story unfolded.
  const chain = [...ancestors].sort((a, b) => b.depth - a.depth);
  const shown = chain.slice(-3);

  return (
    <section aria-labelledby={`lineage-${workId}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 id={`lineage-${workId}`} className="text-sm font-semibold">
          {t('lineage')}
          <span className="tabular ml-2 text-xs font-normal text-muted">
            {t('remix')} {formatCount(descendantCount, locale)}
          </span>
        </h2>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex items-center gap-0.5 text-xs text-muted hover:text-text"
        >
          {t('viewLineage')}
          <IconChevronRight className="size-3.5" />
        </button>
      </div>

      <ol className="flex items-start gap-1 overflow-x-auto pb-1">
        {shown.map((ancestor) => (
          <li key={ancestor.work_version_id} className="flex items-start gap-1">
            <Node
              name={ancestor.author?.display_name ?? tPanel('tombstone')}
              avatar={ancestor.author?.avatar_url}
              caption={ancestor.depth === chain.length ? t('original') : t('remix')}
              tombstone={ancestor.is_tombstone}
            />
            <IconArrowRight className="mt-4 size-4 shrink-0 text-muted" />
          </li>
        ))}

        <li>
          <Node
            name={author.display_name}
            avatar={author.avatar_url}
            caption={t('remix')}
            current
          />
        </li>

        {descendantCount > 0 ? (
          <li className="flex items-start gap-1">
            <IconArrowRight className="mt-4 size-4 shrink-0 text-muted" />
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="flex w-16 flex-col items-center gap-1.5"
            >
              <span className="tabular grid size-10 place-items-center rounded-full border border-border bg-surface-soft text-xs font-medium">
                {formatCount(descendantCount, locale)}+
              </span>
              <span className="text-[11px] text-muted">{tPanel('descendants')}</span>
            </button>
          </li>
        ) : null}
      </ol>

      {open ? <LineageDialog workId={workId} open={open} onClose={() => setOpen(false)} /> : null}
    </section>
  );
}

function Node({
  name,
  avatar,
  caption,
  tombstone,
  current,
}: {
  name: string;
  avatar?: string | null;
  caption: string;
  tombstone?: boolean;
  current?: boolean;
}) {
  return (
    <div className="flex w-16 flex-col items-center gap-1.5 text-center">
      {tombstone ? (
        <span className="grid size-10 place-items-center rounded-full border border-dashed border-border text-muted">
          <IconTombstone className="size-4" />
        </span>
      ) : (
        <Avatar src={avatar} name={name} className={current ? 'ring-2 ring-primary' : undefined} />
      )}
      <span className="w-full truncate text-[11px] text-text" title={name}>
        {name}
      </span>
      <span className="text-[11px] text-muted">{caption}</span>
    </div>
  );
}
