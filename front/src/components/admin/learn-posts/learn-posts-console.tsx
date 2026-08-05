'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar } from '@/components/admin/filter-bar';
import { LearnBodyView } from '@/components/learn/learn-body-view';
import { Button } from '@/components/ui/button';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { LearnPostAdminView } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

type LearnPostStatus = LearnPostAdminView['status'];

const STATUSES: LearnPostStatus[] = ['pending', 'approved', 'rejected', 'withdrawn'];

const STATUS_TONE: Record<LearnPostStatus, BadgeTone> = {
  pending: 'amber',
  approved: 'success',
  rejected: 'danger',
  withdrawn: 'neutral',
};

const STATUS_LABEL_KEY: Record<
  LearnPostStatus,
  | 'learnPostStatusPending'
  | 'learnPostStatusApproved'
  | 'learnPostStatusRejected'
  | 'learnPostStatusWithdrawn'
> = {
  pending: 'learnPostStatusPending',
  approved: 'learnPostStatusApproved',
  rejected: 'learnPostStatusRejected',
  withdrawn: 'learnPostStatusWithdrawn',
};

export function LearnPostsConsole() {
  const t = useTranslations('admin');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const list = useAdminList<LearnPostAdminView>('/v1/admin/learn-posts', {
    initialFilters: { status: 'pending' },
  });
  const [open, setOpen] = useState<LearnPostAdminView | null>(null);
  const [rejecting, setRejecting] = useState<LearnPostAdminView | null>(null);

  const approve = async () => {
    if (!open) return;
    await adminApi.post(`/v1/admin/learn-posts/${open.id}/approve`);
    notify(t('approve'), 'success');
    list.reload();
    setOpen(null);
  };

  const reject = async (reason: string) => {
    if (!rejecting) return;
    await adminApi.post(`/v1/admin/learn-posts/${rejecting.id}/reject`, { reason });
    notify(t('reject'), 'success');
    list.reload();
    setOpen(null);
  };

  const columns: Array<Column<LearnPostAdminView>> = [
    {
      id: 'title',
      header: t('columnTitle'),
      render: (row) => <span className="text-xs">{row.title}</span>,
    },
    {
      id: 'author',
      header: t('columnAuthor'),
      render: (row) => (
        <span className="font-mono text-[11px] text-muted">{row.author_user_id}</span>
      ),
    },
    {
      id: 'level',
      header: t('columnLevel'),
      render: (row) => <span className="text-xs">{row.level}</span>,
    },
    {
      id: 'status',
      header: t('columnStatus'),
      render: (row) => (
        <Badge tone={STATUS_TONE[row.status]}>{t(STATUS_LABEL_KEY[row.status])}</Badge>
      ),
    },
    {
      id: 'created',
      header: t('columnSubmittedAt'),
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
            label: t('learnPostsFilterStatus'),
            kind: 'select',
            options: STATUSES.map((value) => ({ value, label: t(STATUS_LABEL_KEY[value]) })),
          },
        ]}
        values={list.filters}
        onChange={list.setFilter}
        onReset={list.resetFilters}
      >
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {t('refresh')}
        </Button>
      </FilterBar>

      <div className="mt-3">
        <DataTable
          caption={t('learnPostsTitle')}
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
          open ? (
            <>
              <Button size="sm" variant="danger" onClick={() => setRejecting(open)}>
                {t('reject')}
              </Button>
              {open.status === 'pending' ? (
                <Button size="sm" variant="secondary" onClick={() => void approve()}>
                  {t('approve')}
                </Button>
              ) : null}
            </>
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
                  label: t('columnAuthor'),
                  value: <span className="font-mono text-xs">{open.author_user_id}</span>,
                },
                { label: t('columnLevel'), value: open.level },
                { label: t('columnStatus'), value: t(STATUS_LABEL_KEY[open.status]) },
                { label: t('columnSubmittedAt'), value: formatDateTime(open.created_at, locale) },
                ...(open.reject_reason ? [{ label: t('reject'), value: open.reject_reason }] : []),
              ]}
            />

            <div>
              <p className="mb-1.5 text-xs text-muted">{t('detailSummary')}</p>
              <p className="whitespace-pre-wrap text-sm">{open.summary}</p>
            </div>

            <div>
              <p className="mb-1.5 text-xs text-muted">{t('detailBody')}</p>
              <LearnBodyView
                markdown={open.body_markdown}
                assetUrls={open.asset_urls ?? {}}
                emptyImageLabel={tStates('empty')}
              />
            </div>
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={t('reject')}
        description={t('rejectReasonPrompt')}
        reasonLabel={t('dangerReason')}
        onConfirm={reject}
      />
    </div>
  );
}
