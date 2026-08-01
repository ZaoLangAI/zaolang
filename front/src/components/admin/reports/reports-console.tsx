'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar } from '@/components/admin/filter-bar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { ReportCase } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

type WorkAction = 'hide' | 'tombstone' | 'restore';

const STATUSES = ['open', 'in_review', 'upheld', 'dismissed'] as const;

export function ReportsConsole() {
  const t = useTranslations('adminReports');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<ReportCase>('/v1/admin/reports');
  const [open, setOpen] = useState<ReportCase | null>(null);
  const [resolving, setResolving] = useState<'resolved' | 'rejected' | null>(null);
  const [workAction, setWorkAction] = useState<WorkAction | null>(null);

  const canReview = atLeast(role, 'reviewer');
  const canOperate = atLeast(role, 'operator');

  const resolve = async (status: 'resolved' | 'rejected', note: string) => {
    if (!open) return;
    await adminApi.post(`/v1/admin/reports/${open.id}/resolve`, {
      status,
      resolution_note: note,
    });
    notify(t(status === 'resolved' ? 'uphold' : 'dismiss'), 'success');
    list.reload();
    setOpen(null);
  };

  const actOnWork = async (action: WorkAction, reason: string) => {
    if (!open || open.subject_type !== 'work') return;
    await adminApi.post(
      `/v1/admin/works/${open.subject_id}/${action}`,
      action === 'restore' ? undefined : { reason, confirm: true },
    );
    notify(
      t(action === 'hide' ? 'hideWork' : action === 'tombstone' ? 'tombstoneWork' : 'restoreWork'),
      'success',
    );
  };

  const columns: Array<Column<ReportCase>> = [
    {
      id: 'subject',
      header: t('colSubject'),
      render: (row) => (
        <span className="font-mono text-xs">
          {row.subject_type}/{row.subject_id}
        </span>
      ),
    },
    {
      id: 'reason',
      header: t('colReason'),
      render: (row) => <span className="text-xs">{row.reason}</span>,
    },
    {
      id: 'reporter',
      header: t('colReporter'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">
          {row.reporter_user_id ?? tAdmin('actorSystem')}
        </span>
      ),
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (row) => (
        <Badge
          tone={row.status === 'open' ? 'amber' : row.status === 'upheld' ? 'danger' : 'neutral'}
        >
          {row.status}
        </Badge>
      ),
    },
    {
      id: 'created',
      header: tAdmin('detail'),
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
          {
            id: 'status',
            label: t('colStatus'),
            kind: 'select',
            options: STATUSES.map((value) => ({ value, label: value })),
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

      <DetailDrawer
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open ? `${open.subject_type}/${open.subject_id}` : ''}
        subtitle={open?.reason}
        footer={
          canReview && open?.status === 'open' ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => setResolving('rejected')}>
                {t('dismiss')}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setResolving('resolved')}>
                {t('uphold')}
              </Button>
            </>
          ) : null
        }
      >
        {open ? (
          <div className="flex flex-col gap-6">
            <DetailList
              items={[
                { label: t('colReason'), value: open.reason },
                { label: tAdmin('detail'), value: open.detail ?? '—' },
                {
                  label: t('colReporter'),
                  value: (
                    <span className="font-mono text-xs">
                      {open.reporter_user_id ?? tAdmin('actorSystem')}
                    </span>
                  ),
                },
                { label: t('colStatus'), value: open.status },
                { label: tAdmin('timeline'), value: formatDateTime(open.created_at, locale) },
              ]}
            />

            {open.subject_type === 'work' ? (
              <section className="flex flex-wrap gap-2">
                {canReview ? (
                  <Button size="sm" variant="secondary" onClick={() => setWorkAction('hide')}>
                    {t('hideWork')}
                  </Button>
                ) : null}
                {canOperate ? (
                  <>
                    <Button size="sm" variant="danger" onClick={() => setWorkAction('tombstone')}>
                      {t('tombstoneWork')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void actOnWork('restore', 'restore')}
                    >
                      {t('restoreWork')}
                    </Button>
                  </>
                ) : null}
              </section>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={resolving !== null}
        onClose={() => setResolving(null)}
        title={t(resolving === 'resolved' ? 'uphold' : 'dismiss')}
        description={t('subtitle')}
        reasonLabel={t('resolutionNote')}
        onConfirm={async (reason) => {
          if (resolving) await resolve(resolving, reason);
        }}
      />

      <DangerConfirm
        open={workAction !== null}
        onClose={() => setWorkAction(null)}
        title={t(
          workAction === 'tombstone'
            ? 'tombstoneWork'
            : workAction === 'hide'
              ? 'hideWork'
              : 'restoreWork',
        )}
        description={t('subtitle')}
        reasonLabel={tAdmin('dangerReason')}
        // A tombstone is irreversible, so it also asks for the work id.
        confirmWord={workAction === 'tombstone' ? (open?.subject_id ?? undefined) : undefined}
        onConfirm={async (reason) => {
          if (workAction) await actOnWork(workAction, reason);
        }}
      />
    </div>
  );
}
