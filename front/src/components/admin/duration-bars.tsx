'use client';

import { useLocale, useTranslations } from 'next-intl';

import type { Locale } from '@/i18n/routing';
import { cn } from '@/lib/cn';
import { formatNumber } from '@/lib/format';

export interface DurationSegment {
  key: string;
  label: string;
  ms: number;
  tone: 'success' | 'danger' | 'primary' | 'neutral';
}

const TONE_BAR: Record<DurationSegment['tone'], string> = {
  success: 'bg-success',
  danger: 'bg-danger',
  primary: 'bg-primary',
  neutral: 'bg-muted/60',
};

/**
 * A single stacked horizontal bar, one segment per pipeline stage.
 *
 * A lightweight stand-in for a Gantt chart: this repo has no charting
 * dependency, and one job's handful of stages does not warrant adding one —
 * relative segment width is all that is needed to see which stage ate the time.
 */
export function DurationBars({ segments }: { segments: DurationSegment[] }) {
  const t = useTranslations('adminJobs');
  const locale = useLocale() as Locale;
  const total = segments.reduce((sum, segment) => sum + segment.ms, 0);

  if (segments.length === 0 || total <= 0) {
    return <p className="text-xs text-muted">{t('pipelinePending')}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-soft">
        {segments.map((segment) => (
          <div
            key={segment.key}
            className={cn('h-full', TONE_BAR[segment.tone])}
            style={{ width: `${Math.max((segment.ms / total) * 100, segment.ms > 0 ? 1 : 0)}%` }}
            title={`${segment.label} · ${formatNumber(segment.ms, locale)}ms`}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={cn('size-2 rounded-full', TONE_BAR[segment.tone])} />
            <span className="text-text">{segment.label}</span>
            <span className="tabular">{formatNumber(segment.ms, locale)}ms</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
