'use client';

import { useLocale } from 'next-intl';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

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

const PALETTE: TrendColor[] = ['primary', 'success', 'amber', 'danger', 'muted'];

export interface PieSlice {
  label: string;
  value: number;
}

/**
 * First pie chart in the repo — a channel-share breakdown (e.g. "多少播放
 * 来自抖音 vs 快手"), which neither `TrendChart` nor `BarComparisonChart`
 * frames well: those compare magnitudes, this shows proportion of a whole.
 * Same theming convention: colors come from the shared `TrendColor` map,
 * cycled by slice index since a pie's series count isn't fixed up front.
 */
export function ChannelSharePieChart({
  data,
  emptyTitle,
  height = 220,
}: {
  data: PieSlice[];
  emptyTitle: string;
  height?: number;
}) {
  const locale = useLocale() as Locale;
  const total = data.reduce((sum, slice) => sum + slice.value, 0);

  if (total <= 0) {
    return <EmptyState title={emptyTitle} />;
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius="55%"
            outerRadius="85%"
            paddingAngle={2}
          >
            {data.map((slice, index) => (
              <Cell key={slice.label} fill={SERIES_COLOR[PALETTE[index % PALETTE.length]!]} />
            ))}
          </Pie>
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
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
