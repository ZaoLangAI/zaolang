'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { LogEntry } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

/** Privileged audit actions an operator scans for first. */
const DANGEROUS = new Set([
  'config.rollback',
  'credits.adjust',
  'work.tombstone',
  'user.suspend',
  'user.grant_role',
  'job.terminate',
  'data.reset',
  'data_request.approve_deletion',
]);

const LEVEL_TONE: Record<string, BadgeTone> = {
  info: 'neutral',
  warning: 'amber',
  error: 'danger',
};

export function LogCenterConsole() {
  const t = useTranslations('adminAudit');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;

  const list = useAdminList<LogEntry>('/v1/admin/logs');
  const [open, setOpen] = useState<LogEntry | null>(null);

  const exportCsv = () => {
    const header = [
      'occurred_at',
      'source',
      'level',
      'event',
      'message',
      'actor_user_id',
      'target',
      'occurrence_count',
      'reason',
    ];
    const rows = list.rows.map((row) => [
      row.occurred_at,
      row.source,
      row.level,
      row.event,
      row.message.replaceAll('"', '""'),
      row.actor_user_id ?? '',
      row.target ?? '',
      row.occurrence_count?.toString() ?? '',
      (row.reason ?? '').replaceAll('"', '""'),
    ]);
    const csv = [header, ...rows]
      .map((cells) => cells.map((cell) => `"${cell}"`).join(','))
      .join('\n');

    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `logs-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const columns: Array<Column<LogEntry>> = [
    {
      id: 'source',
      header: t('colSource'),
      render: (row) => <span className="font-mono text-[11px]">{t(`source.${row.source}`)}</span>,
    },
    {
      id: 'event',
      header: t('colEvent'),
      render: (row) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs">{row.event}</span>
          {row.source === 'audit' && DANGEROUS.has(row.event) ? (
            <Badge tone="danger">{t('dangerous')}</Badge>
          ) : null}
          {row.occurrence_count && row.occurrence_count > 1 ? (
            <Badge tone="amber">×{formatNumber(row.occurrence_count, locale)}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      id: 'message',
      header: t('colMessage'),
      render: (row) => <span className="line-clamp-2 text-xs">{row.message}</span>,
    },
    {
      id: 'actor',
      header: t('colActor'),
      render: (row) => (
        <span className="block truncate font-mono text-[11px]">
          {row.actor_user_id ?? tAdmin('actorSystem')}
        </span>
      ),
    },
    {
      id: 'level',
      header: t('colLevel'),
      render: (row) => <Badge tone={LEVEL_TONE[row.level] ?? 'neutral'}>{row.level}</Badge>,
    },
    {
      id: 'occurred',
      header: t('colCreated'),
      render: (row) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.occurred_at, locale)}
        </span>
      ),
    },
  ];

  const before = open?.details?.before as Record<string, unknown> | undefined;
  const after = open?.details?.after as Record<string, unknown> | undefined;
  const detailItems = open
    ? [
        { label: t('colMessage'), value: open.message },
        { label: t('colSource'), value: t(`source.${open.source}`) },
        { label: t('colLevel'), value: open.level },
        {
          label: t('colActor'),
          value: (
            <span className="font-mono text-xs">
              {open.actor_user_id ?? tAdmin('actorSystem')}
            </span>
          ),
        },
        { label: t('colTarget'), value: open.target ?? '—' },
        { label: t('colReason'), value: open.reason ?? '—' },
        {
          label: 'request id',
          value: <span className="font-mono text-xs">{open.request_id ?? '—'}</span>,
        },
        {
          label: 'ip',
          value: <span className="font-mono text-xs">{open.ip_address ?? '—'}</span>,
        },
        ...(open.occurrence_count && open.occurrence_count > 1
          ? [{ label: t('colCount'), value: formatNumber(open.occurrence_count, locale) }]
          : []),
        { label: t('colCreated'), value: formatDateTime(open.occurred_at, locale) },
      ]
    : [];

  return (
    <div className="flex flex-col">
      <FilterBar
        filters={[
          {
            id: 'source',
            label: t('filterSource'),
            kind: 'select',
            options: [
              { value: 'audit', label: t('source.audit') },
              { value: 'auth', label: t('source.auth') },
              { value: 'rate_limit', label: t('source.rate_limit') },
              { value: 'permission', label: t('source.permission') },
            ],
          },
          {
            id: 'level',
            label: t('filterLevel'),
            kind: 'select',
            options: [
              { value: 'info', label: 'info' },
              { value: 'warning', label: 'warning' },
              { value: 'error', label: 'error' },
            ],
          },
          { id: 'q', label: t('filterKeyword'), kind: 'text', placeholder: 'login.failed' },
          { id: 'actor_user_id', label: t('colActor'), kind: 'text', placeholder: 'usr_…' },
          { id: 'created', label: t('filterCreated'), kind: 'daterange' },
        ]}
        values={list.filters}
        onChange={list.setFilter}
        onReset={list.resetFilters}
      >
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {tAdmin('refresh')}
        </Button>
        <Button size="sm" variant="ghost" disabled={list.rows.length === 0} onClick={exportCsv}>
          {t('export')}
        </Button>
      </FilterBar>

      <div className="mt-3">
        <DataTable
          caption={t('title')}
          columns={columns}
          rows={list.rows}
          rowKey={(row) => row.id}
          loading={list.loading}
          failed={list.failed}
          activeKey={open?.id}
          onRowClick={setOpen}
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />

      <DetailDrawer
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open?.event ?? ''}
        subtitle={open ? t(`source.${open.source}`) : undefined}
      >
        {open ? (
          <div className="flex flex-col gap-6">
            <DetailList items={detailItems} />

            {before || after ? (
              <section>
                <h3 className="mb-2 text-sm font-semibold">{t('changes')}</h3>
                <JsonDiff before={before ?? {}} after={after ?? {}} />
              </section>
            ) : null}

            {open.details && Object.keys(open.details).length > 0 && !(before || after) ? (
              <section>
                <h3 className="mb-2 text-sm font-semibold">{t('details')}</h3>
                <pre className="overflow-x-auto rounded-[var(--radius-sm)] bg-surface-soft p-3 text-xs">
                  {JSON.stringify(open.details, null, 2)}
                </pre>
              </section>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  );
}
