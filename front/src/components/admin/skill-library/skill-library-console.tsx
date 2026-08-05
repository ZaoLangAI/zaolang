'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar } from '@/components/admin/filter-bar';
import { Button } from '@/components/ui/button';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { CreationSkillAdminView } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

type SkillStatus = CreationSkillAdminView['status'];

const STATUSES: SkillStatus[] = ['draft', 'pending_review', 'published', 'rejected'];

const STATUS_TONE: Record<SkillStatus, BadgeTone> = {
  draft: 'neutral',
  pending_review: 'amber',
  published: 'success',
  rejected: 'danger',
};

const STATUS_LABEL_KEY: Record<
  SkillStatus,
  'skillStatusDraft' | 'skillStatusPendingReview' | 'skillStatusPublished' | 'skillStatusRejected'
> = {
  draft: 'skillStatusDraft',
  pending_review: 'skillStatusPendingReview',
  published: 'skillStatusPublished',
  rejected: 'skillStatusRejected',
};

export function SkillLibraryConsole() {
  const t = useTranslations('adminSkillLibrary');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const list = useAdminList<CreationSkillAdminView>('/v1/admin/skills', {
    initialFilters: { status: 'pending_review' },
  });
  const [open, setOpen] = useState<CreationSkillAdminView | null>(null);
  const [takingDown, setTakingDown] = useState<CreationSkillAdminView | null>(null);

  const takedown = async (reason: string) => {
    if (!takingDown) return;
    await adminApi.post(`/v1/admin/skills/${takingDown.id}/takedown`, { reason, confirm: true });
    notify(t('takedownDone'), 'success');
    list.reload();
    setOpen(null);
    setTakingDown(null);
  };

  const columns: Array<Column<CreationSkillAdminView>> = [
    {
      id: 'title',
      header: t('columnTitle'),
      render: (row) => <span className="text-xs">{row.title}</span>,
    },
    {
      id: 'owner',
      header: t('columnOwner'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">{row.owner_user_id}</span>
      ),
    },
    {
      id: 'category',
      header: t('columnCategory'),
      render: (row) => <span className="text-xs">{row.category}</span>,
    },
    {
      id: 'status',
      header: t('columnStatus'),
      render: (row) => (
        <Badge tone={STATUS_TONE[row.status]}>{t(STATUS_LABEL_KEY[row.status])}</Badge>
      ),
    },
    {
      id: 'usage',
      header: t('columnUsage'),
      render: (row) => (
        <span className="tabular text-xs text-muted">{formatNumber(row.usage_count, locale)}</span>
      ),
    },
    {
      id: 'created',
      header: t('columnCreatedAt'),
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
            label: t('filterStatus'),
            kind: 'select',
            options: STATUSES.map((value) => ({ value, label: t(STATUS_LABEL_KEY[value]) })),
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
        title={open?.title ?? ''}
        subtitle={open ? t(STATUS_LABEL_KEY[open.status]) : undefined}
        footer={
          open && open.status !== 'rejected' ? (
            <Button size="sm" variant="danger" onClick={() => setTakingDown(open)}>
              {t('takedown')}
            </Button>
          ) : null
        }
      >
        {open ? (
          <div className="flex flex-col gap-6">
            {open.cover_url ? (
              <div>
                <p className="mb-1.5 text-xs text-muted">{t('detailCover')}</p>
                <span className="relative block aspect-video w-full overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                  <Image src={open.cover_url} alt="" fill sizes="480px" className="object-cover" />
                </span>
              </div>
            ) : null}

            <DetailList
              items={[
                {
                  label: t('columnOwner'),
                  value: <span className="font-mono text-xs">{open.owner_user_id}</span>,
                },
                { label: t('columnCategory'), value: open.category },
                { label: t('columnStatus'), value: t(STATUS_LABEL_KEY[open.status]) },
                { label: t('columnUsage'), value: formatNumber(open.usage_count, locale) },
                {
                  label: t('columnCreatedAt'),
                  value: formatDateTime(open.created_at, locale),
                },
                ...(open.reject_reason
                  ? [{ label: t('takedown'), value: open.reject_reason }]
                  : []),
              ]}
            />

            <div>
              <p className="mb-1.5 text-xs text-muted">{t('detailDescription')}</p>
              <p className="whitespace-pre-wrap text-sm">{open.description}</p>
            </div>
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={takingDown !== null}
        onClose={() => setTakingDown(null)}
        title={t('takedown')}
        description={t('takedownReasonPrompt')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={takedown}
      />
    </div>
  );
}
