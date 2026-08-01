'use client';

import { useLocale, useTranslations } from 'next-intl';

import { DataTable, type Column } from '@/components/admin/data-table';
import { Badge } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { DanglingReserve } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

/**
 * A non-empty list here means a job reserved credits and never captured or
 * released them, which is the one credit invariant that silently loses money.
 */
export function DanglingReserves() {
  const t = useTranslations('adminCredits');
  const locale = useLocale() as Locale;

  const list = useAdminList<DanglingReserve>('/v1/admin/credits/dangling');

  const columns: Array<Column<DanglingReserve>> = [
    {
      id: 'job',
      header: 'job',
      render: (row) => <span className="font-mono text-xs">{row.job_id}</span>,
    },
    {
      id: 'user',
      header: t('colUser'),
      render: (row) => <span className="font-mono text-[11px] text-muted">{row.user_id}</span>,
    },
    {
      id: 'amount',
      header: t('colAmount'),
      numeric: true,
      render: (row) => formatNumber(row.amount, locale),
    },
    {
      id: 'age',
      header: t('ageHours'),
      numeric: true,
      render: (row) => (
        <Badge tone={row.age_hours > 24 ? 'danger' : 'amber'}>{row.age_hours.toFixed(1)}h</Badge>
      ),
    },
    {
      id: 'status',
      header: t('colType'),
      render: (row) => <span className="text-xs">{row.job_status}</span>,
    },
    {
      id: 'reserved',
      header: t('colCreated'),
      render: (row) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.reserved_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <section>
      <h2 className="text-sm font-semibold">{t('dangling')}</h2>
      <p className="mb-3 mt-1 text-xs text-muted">{t('danglingHint')}</p>
      <DataTable
        caption={t('dangling')}
        columns={columns}
        rows={list.rows}
        rowKey={(row) => row.job_id}
        loading={list.loading}
        failed={list.failed}
        emptyLabel={t('noDangling')}
      />
    </section>
  );
}
