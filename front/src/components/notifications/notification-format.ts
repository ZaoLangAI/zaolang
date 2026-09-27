import type { useTranslations } from 'next-intl';

import {
  IconAlert,
  IconBell,
  IconCheck,
  IconHeart,
  IconImage,
  IconMessage,
  IconMic,
  IconMusic,
  IconPhone,
  IconRemix,
  IconShield,
  IconSparkle,
  IconUser,
  IconVideo,
  IconWallet,
  IconWand,
} from '@/components/ui/icons';
import type { Notification } from '@/lib/api/types';
import { imageCreationStudioHref, isImageCreationOperation } from '@/lib/image-draft';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';

/**
 * Shared rendering logic for a `Notification`: which group label it belongs
 * under, what its one-line text and icon should be, and where it links to.
 * Used by the full `/notifications` list, the top-bar bell popover, and the
 * right-side creation-status toast stack, so all three read a notification
 * identically.
 */

export const GROUPS = {
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
  draft_published: { key: 'typeModeration' },
  draft_publish_rejected: { key: 'typeModeration' },
  system: { key: 'typeSystem' },
  series_collab_invited: { key: 'typeCollaboration' },
  series_collab_accepted: { key: 'typeCollaboration' },
  series_collab_removed: { key: 'typeCollaboration' },
} as const;

export type IconComponent = (props: { className?: string }) => React.ReactNode;

/** Notifications whose `target_type` upserts in place rather than inserting a new row each time. */
export const CREATION_TARGET_TYPES = new Set([
  'generation_job',
  'editor_export',
  'episode_script',
  'draft',
]);

export function isCreationNotification(item: Notification): boolean {
  return item.target_type != null && CREATION_TARGET_TYPES.has(item.target_type);
}

type TBody = ReturnType<typeof useTranslations>;

const TITLE_KEYS: Record<
  string,
  (
    payload: Record<string, unknown>,
    tBody: TBody,
  ) => {
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
  'notification.script_generating': (p) => ({ key: 'scriptGenerating', params: scriptParams(p) }),
  'notification.script_succeeded': (p) => ({ key: 'scriptSucceeded', params: scriptParams(p) }),
  'notification.script_failed': (p) => ({ key: 'scriptFailed', params: scriptParams(p) }),
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
  'notification.draft_published': (p) => ({
    key: 'draftPublished',
    params: { title: String(p.title ?? '') },
  }),
  'notification.draft_publish_rejected': (p) => ({
    key: 'draftPublishRejected',
    params: { title: String(p.title ?? ''), reason: String(p.public_message ?? '') },
  }),
  'notification.series_collab_invited': (p) => ({
    key: 'seriesCollabInvited',
    params: {
      series: String(p.series_title ?? ''),
      actor_name: String(p.inviter_display_name ?? ''),
    },
  }),
  'notification.series_collab_accepted': (p) => ({
    key: 'seriesCollabAccepted',
    params: {
      series: String(p.series_title ?? ''),
      actor_name: String(p.actor_display_name ?? ''),
    },
  }),
  'notification.series_collab_removed': (p) => ({
    key: 'seriesCollabRemoved',
    params: { series: String(p.series_title ?? '') },
  }),
  'notification.series_collab_left': (p) => ({
    key: 'seriesCollabLeft',
    params: {
      series: String(p.series_title ?? ''),
      actor_name: String(p.actor_display_name ?? ''),
    },
  }),
};

export function notificationText(item: Notification, tBody: TBody): string {
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

function jobParams(payload: Record<string, unknown>, tBody: TBody): Record<string, string> {
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

function scriptParams(payload: Record<string, unknown>): Record<string, string> {
  return { title: String(payload.title ?? '') };
}

function operationLabel(payload: Record<string, unknown>, tBody: TBody): string {
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
    case 'music_generation':
      return tBody('opMusic');
    case 'drama_export':
      return tBody('opDramaExport');
    default:
      return String(payload.operation ?? '');
  }
}

export function notificationVisual(item: Notification): {
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
    const amberOps =
      payload.operation === 'image_to_image' || payload.operation === 'image_to_video';
    return { icon: kindIcon, badge: IconSparkle, tone: amberOps ? 'text-amber' : 'text-primary' };
  }
  if (item.type === 'new_follower') return { icon: IconUser, badge: null, tone: 'text-primary' };
  if (item.type === 'work_liked') return { icon: IconHeart, badge: null, tone: 'text-primary' };
  if (item.type === 'work_remixed') return { icon: IconRemix, badge: null, tone: 'text-primary' };
  if (item.type === 'royalty_received' || item.type === 'access_sold') {
    return { icon: IconWallet, badge: null, tone: 'text-amber' };
  }
  if (item.type === 'draft_published') {
    return { icon: kindIcon, badge: IconCheck, tone: 'text-success' };
  }
  if (item.type === 'draft_publish_rejected') {
    return { icon: kindIcon, badge: IconAlert, tone: 'text-danger' };
  }
  if (item.type === 'moderation') return { icon: IconShield, badge: null, tone: 'text-muted' };
  if (
    item.type === 'series_collab_invited' ||
    item.type === 'series_collab_accepted' ||
    item.type === 'series_collab_removed'
  ) {
    return { icon: IconUser, badge: null, tone: 'text-primary' };
  }
  return { icon: IconBell, badge: null, tone: 'text-muted' };
}

function creationIcon(item: Notification, payload: Record<string, unknown>): IconComponent {
  if (item.target_type === 'draft') return IconSparkle;
  if (item.target_type === 'episode_script') return IconMessage;
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
    case 'music_generation':
      return IconMusic;
    default:
      if (item.type.startsWith('job_')) return IconSparkle;
      return IconBell;
  }
}

export function targetHref(item: Notification): string | null {
  const payload = item.payload ?? {};
  if (item.target_type === 'generation_job' && item.target_id) {
    // Image- and video-creation jobs no longer have a standalone progress
    // page to land on (see `ImageGenerationStudio`/`VideoGenerationStudio`);
    // route back into the studio's inline flow instead of `/jobs/[jobId]`
    // when we know which draft it belongs to. Audio/shortform and either
    // media type's jobs without a draft (e.g. sandbox runs) fall back to
    // the job page.
    const draftId = payload.draft_id;
    if (typeof draftId === 'string' && draftId) {
      // `draftId` lands in the studio; `jobId` is which attempt this
      // notification is about (a retry is a new job). Without it the
      // studio would resume `Draft.latest_job_id`, which used to stay
      // pointed at the first failed attempt.
      if (isImageCreationOperation(payload.operation)) {
        return imageCreationStudioHref(draftId, item.target_id);
      }
      if (isVideoCreationOperation(payload.operation)) {
        return videoCreationStudioHref(draftId, item.target_id);
      }
    }
    return `/jobs/${item.target_id}`;
  }
  if (item.target_type === 'editor_export') {
    const cutId = payload.cut_id;
    return typeof cutId === 'string' && cutId ? `/create/short/${cutId}` : '/create/short';
  }
  if (item.target_type === 'episode_script' && item.target_id) {
    return `/create/script/${item.target_id}`;
  }
  if (item.target_type === 'draft' && item.target_id) {
    const workId = payload.work_id;
    if (typeof workId === 'string' && workId) return `/work/${workId}`;
    return `/publish/${item.target_id}`;
  }
  if (item.target_type === 'series_collaboration') {
    // Both the invite-accept flow and the owner's member roster live inside
    // `/create/short` (the dashboard's collaboration-invites popover and
    // each series' own collaborators panel) — see `zaolang-editor-drama`.
    return '/create/short';
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
