'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { AuditLog } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

/** Dangerous actions are the ones an auditor scans for first. */
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

export function AuditConsole() {
  const t = useTranslations('adminAudit');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;

  const list = useAdminList<AuditLog>('/v1/admin/audit-logs');
  const [open, setOpen] = useState<AuditLog | null>(null);

  const exportCsv = () => {
    const header = ['created_at', 'actor_user_id', 'actor_roles', 'action', 'target', 'reason'];
    const rows = list.rows.map((row) => [
      row.created_at,
      row.actor_user_id ?? '',
      row.actor_roles ?? '',
      row.action,
      `${row.target_type}/${row.target_id ?? ''}`,
      (row.reason ?? '').replaceAll('"', '""'),
    ]);
    const csv = [header, ...rows]
      .map((cells) => cells.map((cell) => `"${cell}"`).join(','))
      .join('\n');

    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const columns: Array<Column<AuditLog>> = [
    {
      id: 'action',
      header: t('colAction'),
      render: (row) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs">{row.action}</span>
          {DANGEROUS.has(row.action) ? <Badge tone="danger">{t('dangerous')}</Badge> : null}
        </span>
      ),
    },
    {
      id: 'actor',
      header: t('colActor'),
      render: (row) => (
        <span className="min-w-0">
          <span className="block truncate font-mono text-[11px]">
            {row.actor_user_id ?? tAdmin('actorSystem')}
          </span>
          <span className="block text-[11px] text-muted">{row.actor_roles ?? '—'}</span>
        </span>
      ),
    },
    {
      id: 'target',
      header: t('colTarget'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">
          {row.target_type}/{row.target_id ?? '—'}
        </span>
      ),
    },
    {
      id: 'reason',
      header: t('colReason'),
      render: (row) => <span className="text-xs">{row.reason ?? '—'}</span>,
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
    <div className="flex flex-col">
      <FilterBar
        filters={[
          { id: 'action', label: t('colAction'), kind: 'text', placeholder: 'config.update' },
          { id: 'actor_user_id', label: t('colActor'), kind: 'text', placeholder: 'usr_…' },
          { id: 'target_type', label: t('colTarget'), kind: 'text', placeholder: 'work' },
          { id: 'target_id', label: 'target id', kind: 'text' },
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
        title={open?.action ?? ''}
        subtitle={open ? `${open.target_type}/${open.target_id ?? ''}` : undefined}
      >
        {open ? (
          <div className="flex flex-col gap-6">
            <DetailList
              items={[
                {
                  label: t('colActor'),
                  value: (
                    <span className="font-mono text-xs">
                      {open.actor_user_id ?? tAdmin('actorSystem')}
                      {open.actor_roles ? ` (${open.actor_roles})` : ''}
                    </span>
                  ),
                },
                { label: t('colReason'), value: open.reason ?? '—' },
                {
                  label: 'request id',
                  value: <span className="font-mono text-xs">{open.request_id ?? '—'}</span>,
                },
                {
                  label: 'ip',
                  value: <span className="font-mono text-xs">{open.ip_address ?? '—'}</span>,
                },
                {
                  label: 'user agent',
                  value: <span className="text-xs">{open.user_agent ?? '—'}</span>,
                },
                { label: t('colCreated'), value: formatDateTime(open.created_at, locale) },
              ]}
            />

            <section>
              <h3 className="mb-2 text-sm font-semibold">{t('changes')}</h3>
              <JsonDiff before={open.before_json ?? {}} after={open.after_json ?? {}} />
            </section>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  );
}
