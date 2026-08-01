'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { RoleEditor } from '@/components/admin/users/role-editor';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { AdminUser } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

const STATUSES = ['active', 'suspended', 'deleted'] as const;

export function UsersConsole() {
  const t = useTranslations('adminUsers');
  const tAdmin = useTranslations('admin');
  const tCredits = useTranslations('adminCredits');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<AdminUser>('/v1/admin/users');
  const [open, setOpen] = useState<AdminUser | null>(null);
  const [danger, setDanger] = useState<'suspend' | 'adjust' | null>(null);
  const [adjustAmount, setAdjustAmount] = useState('0');

  const canOperate = atLeast(role, 'operator');
  const isAdmin = atLeast(role, 'admin');

  const statusLabel = (status: string) =>
    status === 'active'
      ? t('statusActive')
      : status === 'suspended'
        ? t('statusSuspended')
        : t('statusDeleted');

  const suspend = async (reason: string) => {
    if (!open) return;
    await adminApi.post(`/v1/admin/users/${open.id}/suspend`, { reason, confirm: true });
    notify(t('suspend'), 'success');
    list.reload();
    setOpen(null);
  };

  const unsuspend = async () => {
    if (!open) return;
    await adminApi.post(`/v1/admin/users/${open.id}/unsuspend`, {
      reason: 'lifted',
      confirm: true,
    });
    notify(t('unsuspend'), 'success');
    list.reload();
    setOpen(null);
  };

  const adjust = async (reason: string) => {
    if (!open) return;
    await adminApi.post(`/v1/admin/users/${open.id}/credits/adjust`, {
      amount: Number(adjustAmount),
      reason,
      confirm: true,
    });
    notify(tCredits('adjust'), 'success');
    list.reload();
  };

  const columns: Array<Column<AdminUser>> = [
    {
      id: 'user',
      header: t('colUser'),
      render: (row) => (
        <span className="min-w-0">
          <span className="block truncate text-xs">{row.display_name ?? row.email}</span>
          <span className="block truncate font-mono text-[11px] text-muted">{row.email}</span>
        </span>
      ),
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (row) => (
        <Badge
          tone={
            row.status === 'active' ? 'success' : row.status === 'suspended' ? 'danger' : 'neutral'
          }
        >
          {statusLabel(row.status)}
        </Badge>
      ),
    },
    {
      id: 'roles',
      header: t('colRoles'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">{row.roles.join(', ')}</span>
      ),
    },
    {
      id: 'credits',
      header: tCredits('colBalance'),
      numeric: true,
      render: (row) =>
        `${formatNumber(row.available_credits, locale)}${row.reserved_credits ? ` (+${formatNumber(row.reserved_credits, locale)})` : ''}`,
    },
    { id: 'works', header: t('colWorks'), numeric: true, render: (row) => row.work_count },
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
          { id: 'q', label: tAdmin('search'), kind: 'text' },
          {
            id: 'status',
            label: t('colStatus'),
            kind: 'select',
            options: STATUSES.map((value) => ({ value, label: statusLabel(value) })),
          },
          {
            id: 'role',
            label: t('colRoles'),
            kind: 'select',
            options: ['user', 'reviewer', 'operator', 'admin'].map((value) => ({
              value,
              label: value,
            })),
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

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />

      <DetailDrawer
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open?.display_name ?? open?.email ?? ''}
        subtitle={open?.id}
        footer={
          canOperate && open ? (
            open.status === 'suspended' ? (
              <Button size="sm" variant="secondary" onClick={() => void unsuspend()}>
                {t('unsuspend')}
              </Button>
            ) : (
              <Button size="sm" variant="danger" onClick={() => setDanger('suspend')}>
                {t('suspend')}
              </Button>
            )
          ) : null
        }
      >
        {open ? (
          <div className="flex flex-col gap-6">
            <DetailList
              items={[
                { label: t('colUser'), value: open.email },
                { label: 'handle', value: open.handle ?? '—' },
                { label: t('colStatus'), value: statusLabel(open.status) },
                { label: 'region', value: open.region },
                {
                  label: tCredits('colBalance'),
                  value: `${formatNumber(open.available_credits, locale)} / ${formatNumber(open.reserved_credits, locale)}`,
                },
                { label: t('colWorks'), value: formatNumber(open.work_count, locale) },
                { label: t('colCreated'), value: formatDateTime(open.created_at, locale) },
                {
                  label: 'last login',
                  value: open.last_login_at ? formatDateTime(open.last_login_at, locale) : '—',
                },
              ]}
            />

            {isAdmin ? (
              <RoleEditor
                userId={open.id}
                roles={open.roles}
                onSaved={() => {
                  list.reload();
                  setOpen(null);
                }}
              />
            ) : null}

            {canOperate ? (
              <section>
                <h3 className="mb-2 text-sm font-semibold">{tCredits('adjust')}</h3>
                <div className="flex items-end gap-3">
                  <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
                    {tCredits('adjustAmount')}
                    <input
                      type="number"
                      value={adjustAmount}
                      onChange={(event) => setAdjustAmount(event.target.value)}
                      className="tabular h-9 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 text-sm text-text"
                    />
                  </label>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={Number(adjustAmount) === 0}
                    onClick={() => setDanger('adjust')}
                  >
                    {tAdmin('apply')}
                  </Button>
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={danger === 'suspend'}
        onClose={() => setDanger(null)}
        title={t('suspend')}
        description={t('subtitle')}
        reasonLabel={t('suspendReason')}
        onConfirm={suspend}
      />

      <DangerConfirm
        open={danger === 'adjust'}
        onClose={() => setDanger(null)}
        title={tCredits('adjust')}
        // A manual adjustment cannot be deleted, only offset by another one, so
        // the reason is the only record of why the balance moved.
        description={tCredits('subtitle')}
        reasonLabel={tCredits('adjustReason')}
        onConfirm={adjust}
      />
    </div>
  );
}
