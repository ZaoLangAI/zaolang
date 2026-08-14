'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  IconAlert,
  IconBell,
  IconCheck,
  IconHeart,
  IconImage,
  IconMessage,
  IconMic,
  IconPhone,
  IconRemix,
  IconShield,
  IconSparkle,
  IconUser,
  IconVideo,
  IconWallet,
  IconWand,
} from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { Notification } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

const NOTIFICATIONS_CHANGED = 'zl-notifications-changed';

const GROUPS = {
  work_remixed: { key: 'typeRemix' },
  work_liked: { key: 'typeLike' },
  new_follower: { key: 'typeFollow' },
  job_progress: { key: 'typeJob' },
  job_succeeded: { key: 'typeJob' },
  job_failed: { key: 'typeJob' },
  job_cancelled: { key: 'typeJob' },
  royalty_received: { key: 'typeRoyalty' },
  access_sold: { key: 'typeAccessSold' },
  moderation: { key: 'typeModeration' },
  system: { key: 'typeSystem' },
} as const;

type IconComponent = (props: { className?: string }) => React.ReactNode;

export function NotificationList({ initial }: { initial: Notification[] }) {
  const t = useTranslations('notificationsPage');
  const tBody = useTranslations('notificationBody');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const [items, setItems] = useState(initial);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [busy, setBusy] = useState(false);

  const unread = items.filter((item) => !item.read).length;
  const shown = filter === 'unread' ? items.filter((item) => !item.read) : items;

  const markAll = async () => {
    setBusy(true);
    try {
      await api.post('/v1/notifications/read');
      setItems((current) => current.map((item) => ({ ...item, read: true })));
      window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
      notify(t('allRead'), 'success');
    } finally {
      setBusy(false);
    }
  };

  const markOne = async (id: string) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, read: true } : item)));
    await api.post('/v1/notifications/read', undefined, { query: { notification_id: id } });
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  };

  if (items.length === 0) {
    return <EmptyState title={t('empty')} description={t('emptyHint')} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label={t('title')} className="flex gap-2">
          {(['all', 'unread'] as const).map((id) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                'rounded-full border px-3.5 py-1.5 text-xs transition-colors',
                filter === id
                  ? 'border-primary bg-primary/12 text-primary'
                  : 'border-border text-muted hover:text-text',
              )}
            >
              {id === 'all' ? t('filterAll') : t('filterUnread')}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <span className="tabular text-xs text-muted">{t('unreadCount', { count: unread })}</span>
          <Button
            size="sm"
            variant="secondary"
            loading={busy}
            disabled={unread === 0}
            onClick={() => void markAll()}
          >
            {t('markAllRead')}
          </Button>
        </div>
      </div>

      {shown.length === 0 ? (
        <EmptyState title={t('empty')} description={t('emptyHint')} />
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface">
          {shown.map((item) => {
            const group = GROUPS[item.type as keyof typeof GROUPS] ?? GROUPS.system;
            const visual = notificationVisual(item);
            const Icon = visual.icon;
            const Badge = visual.badge;
            const href = targetHref(item);

            return (
              <li
                key={item.id}
                className={cn('flex gap-3 px-5 py-4', !item.read && 'bg-primary/4')}
              >
                <span
                  className={cn(
                    'relative mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-surface-soft',
                    visual.tone,
                  )}
                >
                  <Icon className="size-4" />
                  {Badge ? (
                    <span className="absolute -bottom-0.5 -right-0.5 grid size-3.5 place-items-center rounded-full bg-surface">
                      <Badge className="size-2.5" />
                    </span>
                  ) : null}
                </span>

                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-xs text-muted">
                    {t(group.key)}
                    {!item.read ? (
                      <span
                        aria-hidden="true"
                        className="inline-block size-1.5 rounded-full bg-primary"
                      />
                    ) : null}
                  </p>
                  <p className="mt-1 text-sm">{notificationText(item, tBody)}</p>
                  <p className="mt-1 text-xs text-muted">
                    {formatRelative(item.updated_at ?? item.created_at, locale)}
                  </p>
                </div>

                {href ? (
                  <Link
                    href={href}
                    onClick={() => void markOne(item.id)}
                    className="shrink-0 self-center text-xs text-primary hover:underline"
                  >
                    {t('open')}
                  </Link>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const TITLE_KEYS: Record<
  string,
  (payload: Record<string, unknown>, tBody: ReturnType<typeof useTranslations>) => {
    key: string;
    params?: Record<string, string>;
  }
> = {
  'notification.work_approved': () => ({ key: 'workApproved' }),
  'notification.work_hidden': (p) =>
    p.reason
      ? { key: 'workHiddenReason', params: { reason: String(p.reason) } }
      : { key: 'workHidden' },
  'notification.work_restored': () => ({ key: 'workRestored' }),
  'notification.work_tombstoned': (p) => ({
    key: 'workTombstoned',
    params: { reason: String(p.reason ?? '') },
  }),
  'notification.appeal_granted': () => ({ key: 'appealGranted' }),
  'notification.appeal_denied': (p) =>
    p.note
      ? { key: 'appealDeniedReason', params: { note: String(p.note) } }
      : { key: 'appealDenied' },
  'notification.skill_approved': (p) => ({
    key: 'skillApproved',
    params: { title: String(p.title ?? '') },
  }),
  'notification.skill_rejected': (p) => ({
    key: 'skillRejected',
    params: { title: String(p.title ?? ''), reason: String(p.reason ?? '') },
  }),
  'notification.skill_takedown': (p) => ({
    key: 'skillTakedown',
    params: { title: String(p.title ?? ''), reason: String(p.reason ?? '') },
  }),
  'notification.learn_post_approved': (p) => ({
    key: 'learnPostApproved',
    params: { title: String(p.title ?? '') },
  }),
  'notification.learn_post_rejected': (p) => ({
    key: 'learnPostRejected',
    params: { title: String(p.title ?? ''), reason: String(p.reason ?? '') },
  }),
  'notification.job_queued': (p, tBody) => ({
    key: 'jobQueued',
    params: jobParams(p, tBody),
  }),
  'notification.job_running': (p, tBody) => ({
    key: 'jobRunning',
    params: jobParams(p, tBody),
  }),
  'notification.job_awaiting_input': (p, tBody) => ({
    key: 'jobAwaitingInput',
    params: jobParams(p, tBody),
  }),
  'notification.job_succeeded': (p, tBody) => ({
    key: 'jobSucceeded',
    params: jobParams(p, tBody),
  }),
  'notification.job_failed': (p, tBody) => ({
    key: 'jobFailed',
    params: jobParams(p, tBody),
  }),
  'notification.job_cancelled': (p, tBody) => ({
    key: 'jobCancelled',
    params: jobParams(p, tBody),
  }),
  'notification.job_expired': (p, tBody) => ({
    key: 'jobExpired',
    params: jobParams(p, tBody),
  }),
  'notification.export_queued': (p) => ({ key: 'exportQueued', params: exportParams(p) }),
  'notification.export_running': (p) => ({ key: 'exportRunning', params: exportParams(p) }),
  'notification.export_succeeded': (p) => ({ key: 'exportSucceeded', params: exportParams(p) }),
  'notification.export_failed': (p) => ({ key: 'exportFailed', params: exportParams(p) }),
  'notification.export_cancelled': (p) => ({ key: 'exportCancelled', params: exportParams(p) }),
  'notification.work_remixed': (p) => ({
    key: 'workRemixed',
    params: { work_title: String(p.work_title ?? '') },
  }),
  'notification.royalty_received': (p) => ({
    key: 'royaltyReceived',
    params: { work_title: String(p.work_title ?? ''), amount: String(p.amount ?? '') },
  }),
  'notification.access_sold': (p): { key: string; params: Record<string, string> } => {
    const amount = String(p.amount ?? '');
    if (p.subject_type === 'skill') {
      return {
        key: 'accessSoldSkill',
        params: { title: String(p.title ?? ''), amount },
      };
    }
    return { key: 'accessSoldWork', params: { amount } };
  },
  'notification.new_follower': (p) => ({
    key: 'newFollower',
    params: { actor_name: String(p.follower_display_name || p.actor_name || '') },
  }),
  'notification.announcement': () => ({ key: 'announcement' }),
};

function notificationText(item: Notification, tBody: ReturnType<typeof useTranslations>): string {
  const payload = item.payload ?? {};
  const mapped = TITLE_KEYS[item.title_key];
  if (mapped) {
    const { key, params } = mapped(payload, tBody);
    return tBody(key, params);
  }
  const parts = ['title', 'work_title', 'actor_name', 'message']
    .map((field) => payload[field])
    .filter((value): value is string => typeof value === 'string');
  return parts[0] ?? item.title_key;
}

function jobParams(
  payload: Record<string, unknown>,
  tBody: ReturnType<typeof useTranslations>,
): Record<string, string> {
  return {
    operation: operationLabel(payload, tBody),
    excerpt: String(payload.prompt_excerpt ?? ''),
    tier: String(payload.quality_tier ?? ''),
  };
}

function exportParams(payload: Record<string, unknown>): Record<string, string> {
  return {
    series: String(payload.series_title ?? ''),
    episode: String(payload.episode_title ?? ''),
  };
}

function operationLabel(
  payload: Record<string, unknown>,
  tBody: ReturnType<typeof useTranslations>,
): string {
  if (payload.is_remix === true) return tBody('opRemix');
  if (typeof payload.shortform_profile === 'string' && payload.shortform_profile) {
    return tBody('opShortform');
  }
  switch (payload.operation) {
    case 'text_to_image':
      return tBody('opTextToImage');
    case 'image_to_image':
      return tBody('opImageToImage');
    case 'text_to_video':
      return tBody('opTextToVideo');
    case 'image_to_video':
      return tBody('opImageToVideo');
    case 'video_to_video':
      return tBody('opVideoToVideo');
    case 'audio_generation':
      return tBody('opAudio');
    case 'drama_export':
      return tBody('opDramaExport');
    default:
      return String(payload.operation ?? '');
  }
}

function notificationVisual(item: Notification): {
  icon: IconComponent;
  badge: IconComponent | null;
  tone: string;
} {
  const payload = item.payload ?? {};
  const status = String(payload.status ?? '');
  const kindIcon = creationIcon(item, payload);
  if (status === 'succeeded' || item.type === 'job_succeeded') {
    return { icon: kindIcon, badge: IconCheck, tone: 'text-success' };
  }
  if (status === 'failed' || status === 'expired' || item.type === 'job_failed') {
    return { icon: kindIcon, badge: IconAlert, tone: 'text-danger' };
  }
  if (status === 'cancelled' || item.type === 'job_cancelled') {
    return { icon: kindIcon, badge: null, tone: 'text-muted' };
  }
  if (status === 'awaiting_input') {
    return { icon: kindIcon, badge: IconMessage, tone: 'text-amber' };
  }
  if (item.type === 'job_progress') {
    const amberOps = payload.operation === 'image_to_image' || payload.operation === 'image_to_video';
    return { icon: kindIcon, badge: IconSparkle, tone: amberOps ? 'text-amber' : 'text-primary' };
  }
  if (item.type === 'new_follower') return { icon: IconUser, badge: null, tone: 'text-primary' };
  if (item.type === 'work_liked') return { icon: IconHeart, badge: null, tone: 'text-primary' };
  if (item.type === 'work_remixed') return { icon: IconRemix, badge: null, tone: 'text-primary' };
  if (item.type === 'royalty_received' || item.type === 'access_sold') {
    return { icon: IconWallet, badge: null, tone: 'text-amber' };
  }
  if (item.type === 'moderation') return { icon: IconShield, badge: null, tone: 'text-muted' };
  return { icon: IconBell, badge: null, tone: 'text-muted' };
}

function creationIcon(item: Notification, payload: Record<string, unknown>): IconComponent {
  if (payload.is_remix === true) return IconRemix;
  if (typeof payload.shortform_profile === 'string' && payload.shortform_profile) return IconPhone;
  switch (payload.operation) {
    case 'text_to_image':
      return IconImage;
    case 'image_to_image':
      return IconWand;
    case 'text_to_video':
    case 'video_to_video':
    case 'drama_export':
      return IconVideo;
    case 'image_to_video':
      return IconImage;
    case 'audio_generation':
      return IconMic;
    default:
      if (item.type.startsWith('job_')) return IconSparkle;
      return IconBell;
  }
}

function targetHref(item: Notification): string | null {
  const payload = item.payload ?? {};
  if (item.target_type === 'generation_job' && item.target_id) {
    return `/jobs/${item.target_id}`;
  }
  if (item.target_type === 'editor_export') {
    const cutId = payload.cut_id;
    return typeof cutId === 'string' && cutId ? `/create/drama/${cutId}` : '/create/drama';
  }
  if (item.target_type === 'work' && item.target_id) return `/work/${item.target_id}`;
  if (item.target_type === 'learn_post' && item.target_id) return `/learn/${item.target_id}`;
  if (item.target_type === 'skill') return '/skills';
  if (item.target_type === 'user') {
    const handle = payload.follower_handle;
    return typeof handle === 'string' && handle ? `/profile/${handle}` : null;
  }
  return null;
}

export { NOTIFICATIONS_CHANGED };
