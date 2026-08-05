'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { ModerationItem, ModerationSubjectDetail } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

const STATUS_LABEL_KEY: Record<string, string> = {
  pending: 'statusPending',
  approved: 'statusApproved',
  rejected: 'statusRejected',
  needs_review: 'statusNeedsReview',
};

const STATUS_TONE: Record<string, BadgeTone> = {
  pending: 'neutral',
  approved: 'success',
  rejected: 'danger',
  needs_review: 'amber',
};

const LIFECYCLE_LABEL_KEY: Record<string, string> = {
  active: 'lifecycleActive',
  hidden: 'lifecycleHidden',
  tombstone: 'lifecycleTombstone',
};

const VISIBILITY_LABEL_KEY: Record<string, string> = {
  public_remixable: 'visibilityPublicRemixable',
  public_view_only: 'visibilityPublicViewOnly',
  private: 'visibilityPrivate',
};

export function ModerationQueue() {
  const t = useTranslations('adminModeration');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role, session } = useAdminSession();

  const list = useAdminList<ModerationItem>('/v1/admin/moderation/queue');
  const [rejecting, setRejecting] = useState<ModerationItem | null>(null);
  const [viewing, setViewing] = useState<ModerationItem | null>(null);
  const [detail, setDetail] = useState<ModerationSubjectDetail | null>(null);
  const detailLoading = viewing !== null && detail?.queue_item.id !== viewing.id;

  const canReview = atLeast(role, 'reviewer');
  const canRestore = atLeast(role, 'operator');

  useEffect(() => {
    if (!viewing) return;
    let cancelled = false;
    adminApi
      .get<ModerationSubjectDetail>(`/v1/admin/moderation/queue/${viewing.id}/detail`)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [viewing]);

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

  const restore = async () => {
    if (!detail?.work) return;
    await adminApi.post(`/v1/admin/works/${detail.work.id}/restore`);
    notify(t('restored'), 'success');
    setDetail((current) =>
      current?.work
        ? { ...current, work: { ...current.work, lifecycle_status: 'active' } }
        : current,
    );
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
      render: (item) => (
        <span className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setViewing(item)}>
            {tAdmin('detail')}
          </Button>
          {canReview ? (
            <>
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
            </>
          ) : null}
        </span>
      ),
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
        description={t('rejectHint')}
        reasonLabel={t('decisionReason')}
        onConfirm={async (reason) => {
          if (rejecting) await decide(rejecting, 'rejected', reason);
        }}
      />

      <DetailDrawer
        open={viewing !== null}
        onClose={() => {
          setViewing(null);
          setDetail(null);
        }}
        title={viewing?.preview_title ?? viewing?.subject_id ?? ''}
        subtitle={viewing ? `${viewing.subject_type} · ${viewing.stage}` : undefined}
        footer={
          canRestore && detail?.work?.lifecycle_status === 'hidden' ? (
            <Button size="sm" variant="secondary" onClick={() => void restore()}>
              {t('restore')}
            </Button>
          ) : null
        }
      >
        {detailLoading ? <p className="text-xs text-muted">{t('loading')}…</p> : null}
        {!detailLoading && detail ? (
          <div className="flex flex-col gap-5">
            <DetailList
              items={[
                {
                  label: t('colSubject'),
                  value: `${detail.queue_item.subject_type} / ${detail.queue_item.subject_id}`,
                },
                {
                  label: t('colStatus'),
                  value: (
                    <Badge tone={STATUS_TONE[detail.queue_item.status] ?? 'neutral'}>
                      {t(STATUS_LABEL_KEY[detail.queue_item.status] ?? 'statusPending')}
                    </Badge>
                  ),
                },
                {
                  label: t('colLabel'),
                  value: detail.queue_item.reason_code ?? detail.queue_item.stage,
                },
              ]}
            />

            {detail.work ? (
              <div className="flex flex-col gap-3 border-t border-border pt-4">
                {detail.work.cover_url ? (
                  <Poster src={detail.work.cover_url} alt={detail.work.title} aspect="video" />
                ) : null}
                <DetailList
                  items={[
                    { label: t('fieldDescription'), value: detail.work.description ?? '—' },
                    { label: t('fieldPrompt'), value: detail.work.prompt ?? '—' },
                    { label: t('fieldOwner'), value: detail.work.owner_user_id },
                    {
                      label: t('fieldVisibility'),
                      value: t(VISIBILITY_LABEL_KEY[detail.work.visibility] ?? 'visibilityPrivate'),
                    },
                    {
                      label: t('fieldLifecycle'),
                      value: (
                        <Badge
                          tone={detail.work.lifecycle_status === 'active' ? 'success' : 'danger'}
                        >
                          {t(
                            LIFECYCLE_LABEL_KEY[detail.work.lifecycle_status] ?? 'lifecycleActive',
                          )}
                        </Badge>
                      ),
                    },
                    ...(detail.work.tombstone_reason
                      ? [{ label: t('fieldTombstoneReason'), value: detail.work.tombstone_reason }]
                      : []),
                  ]}
                />
              </div>
            ) : null}

            {detail.skill ? (
              <div className="flex flex-col gap-3 border-t border-border pt-4">
                {detail.skill.cover_url ? (
                  <Poster src={detail.skill.cover_url} alt={detail.skill.title} aspect="video" />
                ) : null}
                <DetailList
                  items={[
                    { label: t('fieldDescription'), value: detail.skill.description || '—' },
                    { label: t('fieldCategory'), value: detail.skill.category },
                    { label: t('fieldOwner'), value: detail.skill.owner_user_id },
                    { label: t('fieldUsage'), value: String(detail.skill.usage_count) },
                    ...(detail.skill.reject_reason
                      ? [{ label: t('fieldRejectReason'), value: detail.skill.reject_reason }]
                      : []),
                  ]}
                />
              </div>
            ) : null}

            {!detail.work && !detail.skill ? (
              <p className="text-xs text-muted">{t('noSubjectDetail')}</p>
            ) : null}

            <div className="border-t border-border pt-4">
              <h3 className="mb-2 text-xs font-semibold text-muted">{tAdmin('timeline')}</h3>
              {detail.history.length === 0 ? (
                <p className="text-xs text-muted">{tAdmin('timelineEmpty')}</p>
              ) : (
                <ol className="flex flex-col gap-3">
                  {detail.history.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex flex-col gap-1 border-l-2 border-border pl-3"
                    >
                      <span className="flex items-center gap-2">
                        <Badge tone={STATUS_TONE[entry.status] ?? 'neutral'}>
                          {t(STATUS_LABEL_KEY[entry.status] ?? 'statusPending')}
                        </Badge>
                        <span className="text-xs text-muted">
                          {t(entry.decided_by === 'human' ? 'decidedByHuman' : 'decidedByAgent')}
                        </span>
                      </span>
                      {entry.public_message ? (
                        <p className="text-xs">{entry.public_message}</p>
                      ) : null}
                      {entry.reason_code ? (
                        <p className="font-mono text-[11px] text-muted">{entry.reason_code}</p>
                      ) : null}
                      <span className="tabular text-[11px] text-muted">
                        {formatDateTime(entry.created_at, locale)}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </section>
  );
}
