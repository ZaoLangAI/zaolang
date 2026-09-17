'use client';

import { useLocale } from 'next-intl';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { EmptyState } from '@/components/ui/primitives';
import { DISPLAY_TIME_ZONE, type Locale } from '@/i18n/routing';
import { formatDate, formatNumber, parseInstant } from '@/lib/format';

export type TrendColor = 'primary' | 'success' | 'amber' | 'danger' | 'muted';

const SERIES_COLOR: Record<TrendColor, string> = {
  primary: 'var(--color-primary)',
  success: 'var(--color-success)',
  amber: 'var(--color-amber)',
  danger: 'var(--color-danger)',
  muted: 'var(--color-muted)',
};

export interface TrendSeriesDef {
  /** Key into each data point. */
  dataKey: string;
  label: string;
  color: TrendColor;
}

/**
 * Shared line-chart wrapper — originally built for the admin statistics
 * module (see `duration-bars.tsx` for the stacked-bar/table cases that came
 * before it), now also used by the drama-series analytics pages. A daily
 * trend across a multi-day window is exactly the case a bar/table can't
 * show well, which is why this one pulls in `recharts`.
 */
export function TrendChart<T extends { date: string }>({
  data,
  series,
  emptyTitle,
  height = 220,
  valueFormatter,
}: {
  data: T[];
  series: TrendSeriesDef[];
  emptyTitle: string;
  height?: number;
  /** Overrides plain number formatting on the axis and tooltip — money is
   * stored in micro-USD, which is unreadable as a raw count. */
  valueFormatter?: (value: number) => string;
}) {
  const locale = useLocale() as Locale;
  const hasActivity = data.some((point) =>
    series.some((s) => Number((point as Record<string, unknown>)[s.dataKey] ?? 0) !== 0),
  );

  if (!hasActivity) {
    return <EmptyState title={emptyTitle} />;
  }

  const format = valueFormatter ?? ((value: number) => formatNumber(value, locale));

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(value: string) => formatAxisDate(value, locale)}
            tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
            axisLine={{ stroke: 'var(--color-border)' }}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
            axisLine={false}
            tickLine={false}
            width={valueFormatter ? 60 : 44}
            tickFormatter={format}
          />
          <Tooltip
            labelFormatter={(label) => formatDate(String(label ?? ''), locale)}
            formatter={(value, name) => [format(Number(value ?? 0)), String(name ?? '')]}
            contentStyle={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
            }}
          />
          {series.map((s) => (
            <Line
              key={s.dataKey}
              type="monotone"
              dataKey={s.dataKey}
              name={s.label}
              stroke={SERIES_COLOR[s.color]}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function formatAxisDate(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    timeZone: DISPLAY_TIME_ZONE,
  }).format(parseInstant(value));
}
