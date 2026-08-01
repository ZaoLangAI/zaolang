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
import type { DataRequestView } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

export function DataRequestsPanel() {
  const t = useTranslations('adminUsers');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<DataRequestView>('/v1/admin/data-requests');
  const [pending, setPending] = useState<{ row: DataRequestView; approve: boolean } | null>(null);

  const canOperate = atLeast(role, 'operator');

  const decide = async (reason: string) => {
    if (!pending) return;
    await adminApi.post(`/v1/admin/data-requests/${pending.row.id}/decide`, {
      approve: pending.approve,
      reason,
      confirm: true,
    });
    notify(t(pending.approve ? 'approveRequest' : 'rejectRequest'), 'success');
    list.reload();
  };

  const columns: Array<Column<DataRequestView>> = [
    {
      id: 'type',
      header: t('requestType'),
      render: (row) => (
        <Badge tone={row.type === 'delete' ? 'danger' : 'neutral'}>
          {t(row.type === 'delete' ? 'requestDelete' : 'requestExport')}
        </Badge>
      ),
    },
    {
      id: 'user',
      header: t('colUser'),
      render: (row) => <span className="font-mono text-[11px]">{row.user_id}</span>,
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (row) => <span className="text-xs">{row.status}</span>,
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
    {
      id: 'actions',
      header: tAdmin('apply'),
      render: (row) =>
        canOperate && row.status === 'pending' ? (
          <span className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setPending({ row, approve: true })}
            >
              {t('approveRequest')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPending({ row, approve: false })}>
              {t('rejectRequest')}
            </Button>
          </span>
        ) : null,
    },
  ];

  return (
    <section>
      <h2 className="text-sm font-semibold">{t('dataRequests')}</h2>
      <p className="mb-3 mt-1 text-xs text-muted">{t('dataRequestsHint')}</p>
      <DataTable
        caption={t('dataRequests')}
        columns={columns}
        rows={list.rows}
        rowKey={(row) => row.id}
        loading={list.loading}
        failed={list.failed}
      />

      <DangerConfirm
        open={pending !== null}
        onClose={() => setPending(null)}
        title={t(pending?.approve ? 'approveRequest' : 'rejectRequest')}
        // Approving a deletion anonymises the account; only lineage tombstones
        // survive, so it needs the same friction as a ban.
        description={t('dataRequestsHint')}
        reasonLabel={tAdmin('dangerReason')}
        confirmWord={
          pending?.approve && pending.row.type === 'delete' ? pending.row.user_id : undefined
        }
        onConfirm={decide}
      />
    </section>
  );
}
