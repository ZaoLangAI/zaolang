'use client';

import { useLocale } from 'next-intl';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { EmptyState } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { formatNumber } from '@/lib/format';

import type { TrendColor } from './trend-chart';

const SERIES_COLOR: Record<TrendColor, string> = {
  primary: 'var(--color-primary)',
  success: 'var(--color-success)',
  amber: 'var(--color-amber)',
  danger: 'var(--color-danger)',
  muted: 'var(--color-muted)',
};

export interface BarSeriesDef {
  dataKey: string;
  label: string;
  color: TrendColor;
}

/**
 * First bar chart in the repo — a grouped per-category comparison (e.g. one
 * bar per distribution channel), which a line chart (`TrendChart`) can't
 * represent well. Same theming/empty-state conventions as `TrendChart` so
 * the two read as one family wherever they're used together.
 */
export function BarComparisonChart<T extends { label: string }>({
  data,
  series,
  emptyTitle,
  height = 220,
}: {
  data: T[];
  series: BarSeriesDef[];
  emptyTitle: string;
  height?: number;
}) {
  const locale = useLocale() as Locale;
  const hasActivity = data.some((point) =>
    series.some((s) => Number((point as Record<string, unknown>)[s.dataKey] ?? 0) !== 0),
  );

  if (!hasActivity) {
    return <EmptyState title={emptyTitle} />;
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
            axisLine={{ stroke: 'var(--color-border)' }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
            axisLine={false}
            tickLine={false}
            width={44}
            tickFormatter={(value: number) => formatNumber(value, locale)}
          />
          <Tooltip
            formatter={(value, name) => [
              formatNumber(Number(value ?? 0), locale),
              String(name ?? ''),
            ]}
            contentStyle={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
            }}
          />
          {series.map((s) => (
            <Bar
              key={s.dataKey}
              dataKey={s.dataKey}
              name={s.label}
              fill={SERIES_COLOR[s.color]}
              radius={[4, 4, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
