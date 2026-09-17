'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { SubjectThumb } from '@/components/admin/subject-thumb';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { Appeal } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

type Decision = 'granted' | 'denied';

const STATUSES = ['pending', 'granted', 'denied'] as const;

function subjectPreview(subject: Appeal['subject']): {
  url: string | null;
  mediaType: string | null;
} {
  if (!subject) return { url: null, mediaType: null };
  if (subject.cover_url) return { url: subject.cover_url, mediaType: 'image' };
  if (subject.media_type === 'video' && subject.media_url) {
    return { url: subject.media_url, mediaType: 'video' };
  }
  return { url: null, mediaType: subject.media_type ?? null };
}

export function AppealsConsole() {
  const t = useTranslations('adminAppeals');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<Appeal>('/v1/admin/appeals');
  const [open, setOpen] = useState<Appeal | null>(null);
  const [deciding, setDeciding] = useState<Decision | null>(null);

  const canReview = atLeast(role, 'reviewer');

  const decide = async (decision: Decision, note: string) => {
    if (!open) return;
    await adminApi.post(`/v1/admin/appeals/${open.id}/decide`, {
      decision,
      decision_note: note,
    });
    notify(t(decision === 'granted' ? 'grant' : 'deny'), 'success');
    list.reload();
    setOpen(null);
  };

  const columns: Array<Column<Appeal>> = [
    {
      id: 'subject',
      header: t('colSubject'),
      render: (row) => {
        const preview = subjectPreview(row.subject);
        return (
          <span className="flex items-center gap-2.5">
            <SubjectThumb url={preview.url} mediaType={preview.mediaType} />
            <span className="min-w-0">
              <span className="block truncate text-xs" title={row.work_id}>
                {row.subject?.title ?? t('unknownSubject')}
              </span>
              {row.open_report_count > 0 ? (
                <Badge tone="amber">
                  {t('openReportCount')}: {row.open_report_count}
                </Badge>
              ) : null}
            </span>
          </span>
        );
      },
    },
    {
      id: 'appellant',
      header: t('colAppellant'),
      render: (row) => (
        <span className="text-xs">
          {row.owner_display_name ?? row.owner_handle ?? (
            <span className="font-mono text-[11px] text-muted">{row.owner_user_id}</span>
          )}
        </span>
      ),
    },
    {
      id: 'reason',
      header: t('colReason'),
      render: (row) => <span className="block max-w-xs truncate text-xs">{row.reason}</span>,
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (row) => (
        <Badge
          tone={
            row.status === 'pending' ? 'amber' : row.status === 'granted' ? 'success' : 'neutral'
          }
        >
          {row.status}
        </Badge>
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

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />

      <DetailDrawer
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open?.subject?.title ?? t('unknownSubject')}
        subtitle={open?.owner_display_name ?? open?.owner_handle ?? undefined}
        footer={
          canReview && open?.status === 'pending' ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => setDeciding('denied')}>
                {t('deny')}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDeciding('granted')}>
                {t('grant')}
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
                { label: t('hideReasonLabel'), value: open.subject?.hide_reason ?? '—' },
                { label: t('colStatus'), value: open.status },
                {
                  label: t('openReportCount'),
                  value: (
                    <Badge tone={open.open_report_count > 0 ? 'amber' : 'neutral'}>
                      {open.open_report_count}
                    </Badge>
                  ),
                },
                { label: t('colCreated'), value: formatDateTime(open.created_at, locale) },
                ...(open.status !== 'pending'
                  ? [
                      {
                        label: t('handledBy'),
                        value: open.decided_by_display_name ?? open.decided_by_user_id ?? '—',
                      },
                      {
                        label: t('handledAt'),
                        value: open.decided_at ? formatDateTime(open.decided_at, locale) : '—',
                      },
                      { label: t('decisionNote'), value: open.decision_note ?? '—' },
                    ]
                  : []),
              ]}
            />
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={deciding !== null}
        onClose={() => setDeciding(null)}
        title={t(deciding === 'granted' ? 'grant' : 'deny')}
        description={deciding === 'granted' ? t('grantDescription') : t('denyDescription')}
        reasonLabel={t('decisionNote')}
        onConfirm={async (reason) => {
          if (deciding) await decide(deciding, reason);
        }}
      />
    </div>
  );
}
