'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { SubjectThumb } from '@/components/admin/subject-thumb';
import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconClose,
  IconImage,
  IconMic,
  IconVideo,
} from '@/components/ui/icons';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { ModerationItem, ModerationSubjectDetail } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

const DEFAULT_FILTERS = { status: 'needs_review' };

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

const STATUS_ICON = {
  pending: IconClock,
  approved: IconCheck,
  rejected: IconClose,
  needs_review: IconAlert,
} as const;

const MEDIA_TYPE_ICON = {
  image: IconImage,
  video: IconVideo,
  audio: IconMic,
} as const;

const MEDIA_TYPE_LABEL_KEY: Record<string, string> = {
  image: 'mediaTypeImage',
  video: 'mediaTypeVideo',
  audio: 'mediaTypeAudio',
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

const REJECT_REASON_CODES = [
  'PROHIBITED_CONTENT',
  'NONCONSENSUAL_LIKENESS',
  'ILLEGAL_ACTIVITY',
  'HATE_EXTREMISM',
  'COPYRIGHT',
  'SPAM_DUPLICATE',
  'OTHER',
] as const;
const REASON_CODE_LABEL_KEY: Record<string, string> = {
  PROHIBITED_CONTENT: 'reasonProhibitedContent',
  NONCONSENSUAL_LIKENESS: 'reasonNonconsensualLikeness',
  ILLEGAL_ACTIVITY: 'reasonIllegalActivity',
  HATE_EXTREMISM: 'reasonHateExtremism',
  COPYRIGHT: 'reasonCopyright',
  SPAM_DUPLICATE: 'reasonSpamDuplicate',
  OTHER: 'reasonOther',
  agent_uncertain: 'reasonAgentUncertain',
  SANDBOX_OUTPUT: 'reasonSandboxOutput',
};

const STAGE_LABEL_KEY: Record<string, string> = {
  pre_publish: 'stagePrePublish',
  pre_generation: 'stagePreGeneration',
  post_generation: 'stagePostGeneration',
  skill_review: 'stageSkillReview',
};

type WorkAction = 'hide' | 'tombstone' | 'restore';

function readableLabel(
  item: Pick<ModerationItem, 'reason_code' | 'stage'>,
  t: (key: string) => string,
): string {
  if (item.reason_code) {
    const key = REASON_CODE_LABEL_KEY[item.reason_code];
    return key ? t(key) : t('reasonOther');
  }
  if (item.stage) {
    const key = STAGE_LABEL_KEY[item.stage];
    return key ? t(key) : '—';
  }
  return '—';
}

function StatusMark({ status, t }: { status: string; t: (key: string) => string }) {
  const Icon = STATUS_ICON[status as keyof typeof STATUS_ICON] ?? IconClock;
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <Icon className="size-3.5 shrink-0" />
      {t(STATUS_LABEL_KEY[status] ?? 'statusPending')}
    </span>
  );
}

export function ModerationQueue({ configAction }: { configAction?: React.ReactNode }) {
  const t = useTranslations('adminModeration');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<ModerationItem>('/v1/admin/moderation/queue', {
    initialFilters: DEFAULT_FILTERS,
  });
  const [draftFilters, setDraftFilters] = useState<Record<string, string>>(DEFAULT_FILTERS);
  const [rejecting, setRejecting] = useState<ModerationItem | null>(null);
  const [rejectReasonCode, setRejectReasonCode] = useState<string>('OTHER');
  const [viewing, setViewing] = useState<ModerationItem | null>(null);
  const [detail, setDetail] = useState<ModerationSubjectDetail | null>(null);
  const [workAction, setWorkAction] = useState<WorkAction | null>(null);
  const detailLoading = viewing !== null && detail?.queue_item.id !== viewing.id;

  const canReview = atLeast(role, 'reviewer');
  const canOperate = atLeast(role, 'operator');

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

  const refreshDetail = () => {
    if (!viewing) return;
    adminApi
      .get<ModerationSubjectDetail>(`/v1/admin/moderation/queue/${viewing.id}/detail`)
      .then((data) => setDetail(data))
      .catch(() => {});
  };

  const decide = async (item: ModerationItem, decision: 'approved' | 'rejected', note?: string) => {
    await adminApi.post(`/v1/admin/moderation/queue/${item.id}/decide`, {
      decision,
      note,
      reason_code: decision === 'rejected' ? rejectReasonCode : undefined,
    });
    notify(t(decision === 'approved' ? 'approve' : 'reject'), 'success');
    list.reload();
    if (viewing?.id === item.id) refreshDetail();
  };

  const actOnWork = async (action: WorkAction, reason: string) => {
    if (!detail?.work) return;
    await adminApi.post(
      `/v1/admin/works/${detail.work.id}/${action}`,
      action === 'restore' ? undefined : { reason, confirm: true },
    );
    notify(
      t(action === 'hide' ? 'hideWork' : action === 'tombstone' ? 'tombstoneWork' : 'restoreWork'),
      'success',
    );
    refreshDetail();
    list.reload();
  };

  const reviewButtons = (item: ModerationItem) => {
    if (!canReview) return null;
    const showApprove = item.status !== 'approved';
    const showReject = item.status !== 'rejected';
    return (
      <>
        {showApprove ? (
          <Button size="sm" variant="secondary" onClick={() => void decide(item, 'approved')}>
            {t('approve')}
          </Button>
        ) : null}
        {showReject ? (
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              setRejectReasonCode('OTHER');
              setRejecting(item);
            }}
          >
            {t('reject')}
          </Button>
        ) : null}
      </>
    );
  };

  const columns: Array<Column<ModerationItem>> = [
    {
      id: 'subject',
      header: t('colSubject'),
      render: (item) => (
        <span className="flex items-center gap-2.5">
          <SubjectThumb url={item.preview_url} mediaType={item.preview_media_type} />
          <span className="min-w-0">
            <span className="block truncate text-xs">{item.preview_title ?? item.subject_id}</span>
            <span className="block truncate text-[11px] text-muted" title={item.subject_id}>
              {item.owner_display_name ?? item.owner_handle ?? '—'}
            </span>
          </span>
        </span>
      ),
    },
    {
      id: 'media_type',
      header: t('colMediaType'),
      render: (item) => {
        const mediaType = item.preview_media_type;
        if (!mediaType || !(mediaType in MEDIA_TYPE_ICON)) {
          return <span className="text-xs text-muted">—</span>;
        }
        const Icon = MEDIA_TYPE_ICON[mediaType as keyof typeof MEDIA_TYPE_ICON];
        const label = t(MEDIA_TYPE_LABEL_KEY[mediaType] ?? 'mediaTypeImage');
        return (
          <span className="inline-flex items-center text-muted" title={label} aria-label={label}>
            <Icon className="size-4" />
          </span>
        );
      },
    },
    {
      id: 'stage',
      header: t('colLabel'),
      render: (item) => <span className="text-xs">{readableLabel(item, t)}</span>,
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (item) => <StatusMark status={item.status} t={t} />,
    },
    {
      id: 'created',
      header: t('colCreated'),
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
          {reviewButtons(item)}
        </span>
      ),
    },
  ];

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('title')}</h2>
        {configAction}
      </div>

      <FilterBar
        filters={[
          {
            id: 'status',
            label: t('colStatus'),
            kind: 'multiselect',
            options: Object.entries(STATUS_LABEL_KEY).map(([value, key]) => ({
              value,
              label: t(key),
            })),
          },
          {
            id: 'media_type',
            label: t('filterMediaType'),
            kind: 'multiselect',
            options: Object.entries(MEDIA_TYPE_LABEL_KEY).map(([value, key]) => ({
              value,
              label: t(key),
            })),
          },
          {
            id: 'creator',
            label: t('filterCreator'),
            kind: 'text',
            placeholder: t('filterCreatorPlaceholder'),
          },
          {
            id: 'title',
            label: t('filterTitle'),
            kind: 'text',
            placeholder: t('filterTitlePlaceholder'),
          },
          { id: 'created', label: t('filterCreated'), kind: 'daterange' },
        ]}
        values={draftFilters}
        onChange={(id, value) => setDraftFilters((current) => ({ ...current, [id]: value }))}
        onReset={() => {
          setDraftFilters(DEFAULT_FILTERS);
          list.resetFilters();
        }}
        onSearch={() => list.applyFilters(draftFilters)}
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
          rowKey={(item) => item.id}
          loading={list.loading}
          failed={list.failed}
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
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
      >
        <Select
          label={t('rejectReasonCode')}
          value={rejectReasonCode}
          onChange={(event) => setRejectReasonCode(event.target.value)}
          options={REJECT_REASON_CODES.map((code) => ({
            value: code,
            label: t(REASON_CODE_LABEL_KEY[code] ?? 'reasonOther'),
          }))}
        />
      </DangerConfirm>

      <DetailDrawer
        open={viewing !== null}
        onClose={() => {
          setViewing(null);
          setDetail(null);
        }}
        title={viewing?.preview_title ?? viewing?.subject_id ?? ''}
        subtitle={viewing ? readableLabel(viewing, t) : undefined}
      >
        {detailLoading ? <p className="text-xs text-muted">{t('loading')}…</p> : null}
        {!detailLoading && detail ? (
          <div className="flex flex-col gap-5">
            <DetailList
              items={[
                {
                  label: t('colSubject'),
                  value: detail.queue_item.preview_title ?? detail.queue_item.subject_id,
                },
                {
                  label: t('colStatus'),
                  value: (
                    <Badge tone={STATUS_TONE[detail.queue_item.status] ?? 'neutral'}>
                      <StatusMark status={detail.queue_item.status} t={t} />
                    </Badge>
                  ),
                },
                {
                  label: t('colLabel'),
                  value: readableLabel(detail.queue_item, t),
                },
                {
                  label: t('openReportCount'),
                  value: (
                    <Badge tone={detail.open_report_count > 0 ? 'danger' : 'neutral'}>
                      {detail.open_report_count}
                    </Badge>
                  ),
                },
              ]}
            />

            {canReview && viewing ? (
              <section className="flex flex-wrap gap-2">{reviewButtons(detail.queue_item)}</section>
            ) : null}

            {detail.work ? (
              <div className="flex flex-col gap-3 border-t border-border pt-4">
                {detail.work.media_type === 'video' && detail.work.media_url ? (
                  <video src={detail.work.media_url} controls className="w-full bg-black" />
                ) : detail.work.media_type === 'audio' && detail.work.media_url ? (
                  <audio src={detail.work.media_url} controls className="w-full" />
                ) : detail.work.cover_url ? (
                  <Poster src={detail.work.cover_url} alt={detail.work.title} aspect="video" />
                ) : null}
                <DetailList
                  items={[
                    { label: t('fieldDescription'), value: detail.work.description ?? '—' },
                    { label: t('fieldPrompt'), value: detail.work.prompt ?? '—' },
                    {
                      label: t('fieldOwner'),
                      value: (
                        <span title={detail.work.owner_user_id}>
                          {detail.work.owner_display_name ??
                            detail.work.owner_handle ??
                            detail.work.owner_user_id}
                        </span>
                      ),
                    },
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

                <section className="flex flex-wrap gap-2">
                  {canReview && detail.work.lifecycle_status === 'active' ? (
                    <Button size="sm" variant="secondary" onClick={() => setWorkAction('hide')}>
                      {t('hideWork')}
                    </Button>
                  ) : null}
                  {canOperate && detail.work.lifecycle_status !== 'tombstone' ? (
                    <Button size="sm" variant="danger" onClick={() => setWorkAction('tombstone')}>
                      {t('tombstoneWork')}
                    </Button>
                  ) : null}
                  {canOperate && detail.work.lifecycle_status === 'hidden' ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void actOnWork('restore', 'restore')}
                    >
                      {t('restore')}
                    </Button>
                  ) : null}
                </section>
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
                    ...(detail.skill.category === 'character'
                      ? [
                          {
                            label: t('fieldPortraitConsent'),
                            value: detail.skill.character_portrait_consent_at ? (
                              <Badge tone="success">
                                {formatDateTime(detail.skill.character_portrait_consent_at, locale)}
                              </Badge>
                            ) : (
                              <Badge tone="danger">{t('fieldPortraitConsentMissing')}</Badge>
                            ),
                          },
                        ]
                      : []),
                    ...(detail.skill.reject_reason
                      ? [{ label: t('fieldRejectReason'), value: detail.skill.reject_reason }]
                      : []),
                  ]}
                />

                {detail.skill.category === 'character' &&
                (detail.skill.character_reference_assets?.length ?? 0) > 0 ? (
                  <div>
                    <p className="mb-1.5 text-xs font-semibold text-muted">
                      {t('fieldCharacterReferenceAssets')}
                    </p>
                    <ul className="flex flex-wrap gap-2">
                      {(detail.skill.character_reference_assets ?? []).map((asset) => (
                        <li
                          key={asset.asset_id}
                          className="flex w-24 flex-col gap-1 rounded-[var(--radius-sm)] border border-border p-1"
                        >
                          {asset.url ? (
                            <Poster
                              src={asset.url}
                              alt={asset.label ?? asset.view}
                              aspect="square"
                            />
                          ) : null}
                          <span className="truncate text-center text-[10px] text-muted">
                            {asset.label || t(`characterView_${asset.view}`)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {detail.skill.category === 'scene_asset' &&
                (detail.skill.scene_reference_assets?.length ?? 0) > 0 ? (
                  <div>
                    <p className="mb-1.5 text-xs font-semibold text-muted">
                      {t('fieldSceneReferenceAssets')}
                    </p>
                    <ul className="flex flex-wrap gap-2">
                      {(detail.skill.scene_reference_assets ?? []).map((asset) => (
                        <li
                          key={asset.asset_id}
                          className="flex w-24 flex-col gap-1 rounded-[var(--radius-sm)] border border-border p-1"
                        >
                          {asset.url ? (
                            <Poster
                              src={asset.url}
                              alt={asset.label ?? asset.view}
                              aspect="square"
                            />
                          ) : null}
                          <span className="truncate text-center text-[10px] text-muted">
                            {asset.label || asset.view}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}

            {detail.job ? (
              <div className="flex flex-col gap-3 border-t border-border pt-4">
                {detail.job.preview_url ? (
                  detail.job.mime_type?.startsWith('video/') ? (
                    <video src={detail.job.preview_url} controls className="w-full bg-black" />
                  ) : detail.job.mime_type?.startsWith('audio/') ? (
                    <audio src={detail.job.preview_url} controls className="w-full" />
                  ) : (
                    <Poster
                      src={detail.job.preview_url}
                      alt={detail.job.prompt ?? ''}
                      aspect="video"
                    />
                  )
                ) : null}
                <DetailList
                  items={[
                    { label: t('fieldPrompt'), value: detail.job.prompt ?? '—' },
                    { label: t('fieldOperation'), value: detail.job.operation },
                    { label: t('fieldOrigin'), value: detail.job.origin },
                    { label: t('colStatus'), value: detail.job.status },
                  ]}
                />
              </div>
            ) : null}

            {!detail.work && !detail.skill && !detail.job ? (
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
                          <StatusMark status={entry.status} t={t} />
                        </Badge>
                        <span className="text-xs text-muted">
                          {t(entry.decided_by === 'human' ? 'decidedByHuman' : 'decidedByAgent')}
                        </span>
                      </span>
                      {entry.public_message ? (
                        <p className="text-xs">{entry.public_message}</p>
                      ) : null}
                      {entry.reason_code ? (
                        <p className="text-xs text-muted">
                          {t(REASON_CODE_LABEL_KEY[entry.reason_code] ?? 'reasonOther')}
                        </p>
                      ) : null}
                      {entry.categories && entry.categories.length > 0 ? (
                        <span className="flex flex-wrap gap-1">
                          {entry.categories.map((category) => (
                            <Badge key={category} tone="neutral">
                              {category}
                            </Badge>
                          ))}
                        </span>
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
        confirmWord={workAction === 'tombstone' ? (detail?.work?.id ?? undefined) : undefined}
        onConfirm={async (reason) => {
          if (workAction) await actOnWork(workAction, reason);
        }}
      />
    </section>
  );
}
