'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { BackupRecord } from '@/lib/api/admin-types';
import { formatBytes, formatDateTime } from '@/lib/format';

export function BackupsPanel() {
  const t = useTranslations('adminData');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<BackupRecord>('/v1/admin/backups');
  const [confirming, setConfirming] = useState(false);

  const trigger = async (reason: string) => {
    // The request runs pg_dump inline, so it can take a while on a real
    // database; the toast fires only once the archive is stored.
    await adminApi.post('/v1/admin/backups', { kind: 'database', reason, confirm: true });
    notify(t('backupTriggered'), 'success');
    list.reload();
  };

  const columns: Array<Column<BackupRecord>> = [
    {
      id: 'kind',
      header: t('backupKind'),
      render: (row) => <span className="text-xs">{row.kind}</span>,
    },
    {
      id: 'status',
      header: t('backupStatus'),
      render: (row) => (
        <Badge
          tone={
            row.status === 'succeeded' ? 'success' : row.status === 'failed' ? 'danger' : 'amber'
          }
        >
          {row.status}
        </Badge>
      ),
    },
    {
      id: 'size',
      header: t('backupSize'),
      numeric: true,
      render: (row) => (row.size_bytes ? formatBytes(row.size_bytes, locale) : '—'),
    },
    {
      id: 'key',
      header: t('backupObject'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">
          {row.object_key ?? row.message ?? '—'}
        </span>
      ),
    },
    {
      id: 'created',
      header: t('backupCreated'),
      render: (row) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.created_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('backups')}</h2>
        {atLeast(role, 'admin') ? (
          <Button size="sm" variant="secondary" onClick={() => setConfirming(true)}>
            {t('triggerBackup')}
          </Button>
        ) : null}
      </div>
      <p className="mb-3 text-xs text-muted">{t('backupsHint')}</p>

      <DataTable
        caption={t('backups')}
        columns={columns}
        rows={list.rows}
        rowKey={(row) => row.id}
        loading={list.loading}
        failed={list.failed}
      />

      <DangerConfirm
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t('triggerBackup')}
        description={t('backupsHint')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={trigger}
      />
    </section>
  );
}
