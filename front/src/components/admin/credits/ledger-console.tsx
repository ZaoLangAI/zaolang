'use client';

import { useLocale, useTranslations } from 'next-intl';

import { DataTable, type Column } from '@/components/admin/data-table';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { AdminLedgerEntry } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

const ENTRY_TYPES = [
  'topup',
  'reserve',
  'capture',
  'release',
  'refund',
  'adjustment',
  'royalty_in',
  'royalty_out',
] as const;

export function LedgerConsole() {
  const t = useTranslations('adminCredits');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;

  const list = useAdminList<AdminLedgerEntry>('/v1/admin/credits/ledger');

  const columns: Array<Column<AdminLedgerEntry>> = [
    {
      id: 'type',
      header: t('colType'),
      render: (row) => (
        <Badge tone={row.type === 'adjustment' ? 'amber' : 'neutral'}>{row.type}</Badge>
      ),
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
      render: (row) => (
        <span className={row.amount < 0 ? 'text-danger' : 'text-success'}>
          {row.amount > 0 ? '+' : ''}
          {formatNumber(row.amount, locale)}
        </span>
      ),
    },
    {
      id: 'balance',
      header: t('colBalance'),
      numeric: true,
      render: (row) =>
        `${formatNumber(row.balance_after, locale)} / ${formatNumber(row.reserved_after, locale)}`,
    },
    {
      id: 'job',
      header: 'job',
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">{row.job_id ?? '—'}</span>
      ),
    },
    {
      id: 'reason',
      header: t('colReason'),
      render: (row) => (
        <span className="text-xs">
          {row.reason ?? '—'}
          {row.actor_user_id ? (
            <span className="block font-mono text-[11px] text-muted">{row.actor_user_id}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: 'created',
      header: t('colCreated'),
      render: (row) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.created_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <section className="flex flex-col">
      <h2 className="mb-3 text-sm font-semibold">{t('ledger')}</h2>

      <FilterBar
        filters={[
          { id: 'user_id', label: t('colUser'), kind: 'text', placeholder: 'usr_…' },
          { id: 'job_id', label: 'job', kind: 'text', placeholder: 'job_…' },
          {
            id: 'entry_type',
            label: t('colType'),
            kind: 'select',
            options: ENTRY_TYPES.map((value) => ({ value, label: value })),
          },
        ]}
        values={list.filters}
        onChange={list.setFilter}
        onReset={list.resetFilters}
      >
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {tAdmin('refresh')}
        </Button>
      </FilterBar>

      <div className="mt-3">
        <DataTable
          caption={t('ledger')}
          columns={columns}
          rows={list.rows}
          rowKey={(row) => row.id}
          loading={list.loading}
          failed={list.failed}
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />
    </section>
  );
}
