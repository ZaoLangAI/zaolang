'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { Badge, EmptyState } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type {
  Page,
  RedemptionCode,
  RedemptionCodeKind,
  RedemptionRecord,
} from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

interface CreateForm {
  kind: RedemptionCodeKind;
  credits: string;
  maxUses: string;
  expiresAt: string;
  note: string;
  customCode: string;
}

function emptyForm(): CreateForm {
  return { kind: 'promo', credits: '100', maxUses: '1', expiresAt: '', note: '', customCode: '' };
}

/** Invite/promo code issuance: table + create dialog + per-code redemption
 * history. Mirrors `LedgerConsole`'s shape — every credits panel behaves the
 * same way so an operator does not have to relearn the console per section. */
export function RedemptionCodesPanel() {
  const t = useTranslations('adminCredits');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();
  const canOperate = atLeast(role, 'operator');

  const list = useAdminList<RedemptionCode>('/v1/admin/redemption-codes');
  const [creating, setCreating] = useState<CreateForm | null>(null);
  const [pendingCreate, setPendingCreate] = useState<CreateForm | null>(null);
  const [viewing, setViewing] = useState<RedemptionCode | null>(null);
  const [records, setRecords] = useState<{ codeId: string; items: RedemptionRecord[] } | null>(
    null,
  );
  const [deactivating, setDeactivating] = useState<RedemptionCode | null>(null);
  const recordsLoading = viewing !== null && records?.codeId !== viewing.id;

  useEffect(() => {
    if (!viewing) return;
    let cancelled = false;
    adminApi
      .get<Page<RedemptionRecord>>(`/v1/admin/redemption-codes/${viewing.id}/records`)
      .then((page) => {
        if (!cancelled) setRecords({ codeId: viewing.id, items: page.items });
      })
      .catch(() => {
        if (!cancelled) setRecords({ codeId: viewing.id, items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [viewing]);

  const create = async (reason: string) => {
    if (!pendingCreate) return;
    await adminApi.post('/v1/admin/redemption-codes', {
      kind: pendingCreate.kind,
      credits: Number(pendingCreate.credits),
      max_uses: Number(pendingCreate.maxUses),
      expires_at: pendingCreate.expiresAt ? new Date(pendingCreate.expiresAt).toISOString() : null,
      note: pendingCreate.note.trim() || undefined,
      code: pendingCreate.customCode.trim() || undefined,
      reason,
      confirm: true,
    });
    notify(t('codeCreated'), 'success');
    setPendingCreate(null);
    setCreating(null);
    list.reload();
  };

  const deactivate = async (reason: string) => {
    if (!deactivating) return;
    await adminApi.post(`/v1/admin/redemption-codes/${deactivating.id}/deactivate`, {
      reason,
      confirm: true,
    });
    notify(t('deactivated'), 'success');
    setDeactivating(null);
    setViewing(null);
    list.reload();
  };

  const columns: Array<Column<RedemptionCode>> = [
    {
      id: 'code',
      header: t('colCode'),
      render: (row) => <span className="font-mono text-xs">{row.code}</span>,
    },
    {
      id: 'kind',
      header: t('colKind'),
      render: (row) => (
        <Badge tone="neutral">
          {row.kind === 'invite' ? t('codeKindInvite') : t('codeKindPromo')}
        </Badge>
      ),
    },
    {
      id: 'credits',
      header: t('colCredits'),
      numeric: true,
      render: (row) => formatNumber(row.credits, locale),
    },
    {
      id: 'usage',
      header: t('colUsage'),
      numeric: true,
      render: (row) =>
        `${formatNumber(row.used_count, locale)} / ${formatNumber(row.max_uses, locale)}`,
    },
    {
      id: 'expires',
      header: t('colExpires'),
      render: (row) => (
        <span className="whitespace-nowrap text-xs text-muted">
          {row.expires_at ? formatDateTime(row.expires_at, locale) : t('noExpiry')}
        </span>
      ),
    },
    {
      id: 'active',
      header: t('colActive'),
      render: (row) => (
        <Badge tone={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? t('active') : t('inactive')}
        </Badge>
      ),
    },
    {
      id: 'created',
      header: t('colCreated'),
      render: (row) => (
        <span className="whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.created_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <section className="flex flex-col">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t('redemption')}</h2>
          <p className="text-xs text-muted">{t('redemptionHint')}</p>
        </div>
        {canOperate ? (
          <Button size="sm" onClick={() => setCreating(emptyForm())}>
            {t('newCode')}
          </Button>
        ) : null}
      </div>

      <FilterBar
        filters={[
          {
            id: 'kind',
            label: t('colKind'),
            kind: 'select',
            options: [
              { value: 'invite', label: t('codeKindInvite') },
              { value: 'promo', label: t('codeKindPromo') },
            ],
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
          caption={t('redemption')}
          columns={columns}
          rows={list.rows}
          rowKey={(row) => row.id}
          loading={list.loading}
          failed={list.failed}
          onRowClick={setViewing}
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />

      <DetailDrawer
        open={viewing !== null}
        onClose={() => setViewing(null)}
        title={viewing?.code ?? ''}
        subtitle={
          viewing
            ? viewing.kind === 'invite'
              ? t('codeKindInvite')
              : t('codeKindPromo')
            : undefined
        }
        footer={
          canOperate && viewing?.is_active ? (
            <Button variant="danger" onClick={() => setDeactivating(viewing)}>
              {t('deactivate')}
            </Button>
          ) : undefined
        }
      >
        {viewing ? (
          <div className="flex flex-col gap-5">
            <DetailList
              items={[
                { label: t('colCredits'), value: formatNumber(viewing.credits, locale) },
                {
                  label: t('colUsage'),
                  value: `${formatNumber(viewing.used_count, locale)} / ${formatNumber(viewing.max_uses, locale)}`,
                },
                {
                  label: t('colExpires'),
                  value: viewing.expires_at
                    ? formatDateTime(viewing.expires_at, locale)
                    : t('noExpiry'),
                },
                { label: t('colNote'), value: viewing.note ?? '—' },
                { label: t('colCreated'), value: formatDateTime(viewing.created_at, locale) },
              ]}
            />

            <section>
              <h3 className="mb-2 text-sm font-semibold">{t('records')}</h3>
              {recordsLoading ? (
                <p className="text-xs text-muted">{tAdmin('loading')}</p>
              ) : !records || records.items.length === 0 ? (
                <EmptyState title={t('recordsEmpty')} />
              ) : (
                <ul className="flex flex-col divide-y divide-border text-xs">
                  {records.items.map((record) => (
                    <li key={record.id} className="flex items-center justify-between gap-3 py-2">
                      <span className="font-mono text-muted">{record.user_id}</span>
                      <span className="tabular text-success">
                        +{formatNumber(record.credits, locale)}
                      </span>
                      <span className="whitespace-nowrap text-muted">
                        {formatDateTime(record.created_at, locale)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        ) : null}
      </DetailDrawer>

      <Dialog
        open={creating !== null}
        onClose={() => setCreating(null)}
        title={t('createCodeTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(null)}>
              {tAdmin('reset')}
            </Button>
            <Button
              disabled={!creating || Number(creating.credits) <= 0 || Number(creating.maxUses) <= 0}
              onClick={() => {
                if (creating) setPendingCreate(creating);
              }}
            >
              {tAdmin('next')}
            </Button>
          </>
        }
      >
        {creating ? (
          <div className="flex flex-col gap-4">
            <Select
              label={t('fieldKind')}
              value={creating.kind}
              options={[
                { value: 'promo', label: t('codeKindPromo') },
                { value: 'invite', label: t('codeKindInvite') },
              ]}
              onChange={(event) =>
                setCreating(
                  (current) =>
                    current && { ...current, kind: event.target.value as RedemptionCodeKind },
                )
              }
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput
                label={t('fieldCredits')}
                type="number"
                min="1"
                value={creating.credits}
                onChange={(event) =>
                  setCreating((current) => current && { ...current, credits: event.target.value })
                }
              />
              <TextInput
                label={t('fieldMaxUses')}
                type="number"
                min="1"
                value={creating.maxUses}
                onChange={(event) =>
                  setCreating((current) => current && { ...current, maxUses: event.target.value })
                }
              />
            </div>
            <TextInput
              label={t('fieldExpiresAt')}
              type="datetime-local"
              value={creating.expiresAt}
              onChange={(event) =>
                setCreating((current) => current && { ...current, expiresAt: event.target.value })
              }
            />
            <TextInput
              label={t('fieldCustomCode')}
              value={creating.customCode}
              className="font-mono uppercase"
              onChange={(event) =>
                setCreating(
                  (current) =>
                    current && { ...current, customCode: event.target.value.toUpperCase() },
                )
              }
            />
            <TextArea
              label={t('fieldNote')}
              value={creating.note}
              maxLength={300}
              onChange={(event) =>
                setCreating((current) => current && { ...current, note: event.target.value })
              }
            />
          </div>
        ) : null}
      </Dialog>

      <DangerConfirm
        open={pendingCreate !== null}
        onClose={() => setPendingCreate(null)}
        title={t('createCodeTitle')}
        description={t('createDesc')}
        reasonLabel={t('createReasonLabel')}
        onConfirm={create}
      />

      <DangerConfirm
        open={deactivating !== null}
        onClose={() => setDeactivating(null)}
        title={t('deactivate')}
        description={t('deactivateDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={deactivate}
      />
    </section>
  );
}
