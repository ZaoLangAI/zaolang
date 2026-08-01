'use client';

import { useLocale, useTranslations } from 'next-intl';

import type { Locale } from '@/i18n/routing';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';

export interface TimelineEntry {
  id: string;
  at: string;
  label: string;
  detail?: string;
  /** Internal codes are operator-only and never shown to the end user. */
  code?: string;
  tone?: 'neutral' | 'success' | 'danger' | 'amber';
}

/**
 * Ordered replay of what happened to one record.
 *
 * Shows the internal code alongside the public message, because the reason an
 * operator opens this panel is precisely that the public message was not enough.
 */
export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  const t = useTranslations('admin');
  const locale = useLocale() as Locale;

  if (entries.length === 0) {
    return <p className="text-xs text-muted">{t('timelineEmpty')}</p>;
  }

  return (
    <ol className="relative flex flex-col gap-4 border-l border-border pl-5">
      {entries.map((entry) => (
        <li key={entry.id} className="relative">
          <span
            aria-hidden="true"
            className={cn(
              'absolute -left-[23px] top-1.5 size-2.5 rounded-full border-2 border-surface',
              entry.tone === 'success'
                ? 'bg-success'
                : entry.tone === 'danger'
                  ? 'bg-danger'
                  : entry.tone === 'amber'
                    ? 'bg-amber'
                    : 'bg-muted',
            )}
          />
          <p className="text-sm">{entry.label}</p>
          {entry.detail ? <p className="mt-0.5 text-xs text-muted">{entry.detail}</p> : null}
          <p className="tabular mt-0.5 text-[11px] text-muted">
            {formatDateTime(entry.at, locale)}
            {entry.code ? ` · ${entry.code}` : ''}
          </p>
        </li>
      ))}
    </ol>
  );
}
