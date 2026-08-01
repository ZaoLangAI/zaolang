'use client';

import Image from 'next/image';
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
import type { ModerationItem } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

export function ModerationQueue() {
  const t = useTranslations('adminModeration');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role, session } = useAdminSession();

  const list = useAdminList<ModerationItem>('/v1/admin/moderation/queue');
  const [rejecting, setRejecting] = useState<ModerationItem | null>(null);

  const canReview = atLeast(role, 'reviewer');

  const decide = async (item: ModerationItem, decision: 'approved' | 'rejected', note?: string) => {
    await adminApi.post(`/v1/admin/moderation/queue/${item.id}/decide`, {
      decision,
      note,
      reason_code: decision === 'rejected' ? 'manual_review' : undefined,
    });
    notify(t(decision === 'approved' ? 'approve' : 'reject'), 'success');
    list.reload();
  };

  const claim = async (item: ModerationItem) => {
    await adminApi.post(`/v1/admin/moderation/queue/${item.id}/claim`);
    list.reload();
  };

  const columns: Array<Column<ModerationItem>> = [
    {
      id: 'subject',
      header: t('colSubject'),
      render: (item) => (
        <span className="flex items-center gap-2.5">
          {item.preview_url ? (
            <span className="relative size-9 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
              <Image src={item.preview_url} alt="" fill sizes="72px" className="object-cover" />
            </span>
          ) : null}
          <span className="min-w-0">
            <span className="block truncate text-xs">{item.preview_title ?? item.subject_id}</span>
            <span className="block font-mono text-[11px] text-muted">{item.subject_type}</span>
          </span>
        </span>
      ),
    },
    {
      id: 'stage',
      header: t('colLabel'),
      render: (item) => <span className="text-xs">{item.reason_code ?? item.stage}</span>,
    },
    {
      id: 'priority',
      header: t('colScore'),
      numeric: true,
      render: (item) => item.priority,
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (item) => (
        <Badge tone={item.claimed_by_user_id ? 'primary' : 'amber'}>
          {item.claimed_by_user_id === session.user_id
            ? t('claim')
            : (item.claimed_by_user_id ?? item.status)}
        </Badge>
      ),
    },
    {
      id: 'created',
      header: tAdmin('detail'),
      render: (item) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(item.created_at, locale)}
        </span>
      ),
    },
    {
      id: 'actions',
      header: tAdmin('apply'),
      render: (item) =>
        canReview ? (
          <span className="flex gap-2">
            {item.claimed_by_user_id ? null : (
              <Button size="sm" variant="ghost" onClick={() => void claim(item)}>
                {t('claim')}
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => void decide(item, 'approved')}>
              {t('approve')}
            </Button>
            <Button size="sm" variant="danger" onClick={() => setRejecting(item)}>
              {t('reject')}
            </Button>
          </span>
        ) : null,
    },
  ];

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('title')}</h2>
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {tAdmin('refresh')}
        </Button>
      </div>

      <DataTable
        caption={t('title')}
        columns={columns}
        rows={list.rows}
        rowKey={(item) => item.id}
        loading={list.loading}
        failed={list.failed}
      />

      <DangerConfirm
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={t('reject')}
        // Rejecting a work tombstones it, which cannot be undone, so the
        // reviewer has to say why on the record.
        description={t('subtitle')}
        reasonLabel={t('decisionReason')}
        onConfirm={async (reason) => {
          if (rejecting) await decide(rejecting, 'rejected', reason);
        }}
      />
    </section>
  );
}
