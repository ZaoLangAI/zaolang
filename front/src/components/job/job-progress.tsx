'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { DevicePreview } from '@/components/media/device-preview';
import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconCheck, IconClock, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount, formatDateTime } from '@/lib/format';
import { useJobStream } from '@/lib/use-job-stream';
import { loadAnime, useReducedMotion } from '@/lib/motion';

const PROGRESS_DURATION = 650;
const STAGE_POP_DURATION = 420;

/** Ordered stages from the design's progress rail, mapped from event types. */
const STAGES = ['queued', 'planning', 'safety', 'generating', 'sound', 'quality', 'done'] as const;
type Stage = (typeof STAGES)[number];

const STAGE_FOR_EVENT: Record<string, Stage> = {
  created: 'queued',
  queued: 'queued',
  planning: 'planning',
  planned: 'planning',
  safety_checked: 'safety',
  routed: 'generating',
  provider_started: 'generating',
  progress: 'generating',
  sound: 'sound',
  quality_checked: 'quality',
  settled: 'done',
  succeeded: 'done',
};

export function JobProgress({ jobId, initial }: { jobId: string; initial: GenerationJob }) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const router = useRouter();

  const { job, events, reconnecting } = useJobStream(jobId, initial);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const current = job ?? initial;
  const reached = new Set<Stage>();
  for (const event of events) {
    const stage = STAGE_FOR_EVENT[event.event_type];
    if (stage) reached.add(stage);
  }
  if (current.status === 'succeeded') for (const stage of STAGES) reached.add(stage);

  const activeIndex = STAGES.findIndex((stage) => !reached.has(stage));
  const finished = ['succeeded', 'failed', 'cancelled', 'expired'].includes(current.status);
  const reachedKey = STAGES.filter((stage) => reached.has(stage)).join(',');

  const reduced = useReducedMotion();
  // Frozen at mount so React never rewrites `style.width` on a later render —
  // once mounted, the bar is driven purely by the imperative effect below, or
  // this snapshot would race with anime and always win, snapping the value
  // before the animation had a chance to run. State (not a ref) because the
  // value is read during render, for the very first paint's inline style.
  const [initialProgress] = useState(current.progress);
  const barRef = useRef<HTMLDivElement>(null);
  const dotRefs = useRef<Partial<Record<Stage, HTMLSpanElement | null>>>({});
  const previousReachedRef = useRef<Set<Stage>>(new Set());
  const stageAnimationReady = useRef(false);

  useEffect(() => {
    const node = barRef.current;
    if (!node) return;
    if (reduced) {
      node.style.width = `${current.progress}%`;
      return;
    }
    loadAnime().then(({ animate }) => {
      animate(node, {
        width: `${current.progress}%`,
        duration: PROGRESS_DURATION,
        ease: 'outExpo',
      });
    });
  }, [current.progress, reduced]);

  useEffect(() => {
    const previous = previousReachedRef.current;
    previousReachedRef.current = reached;
    // Skip the first snapshot: a job opened mid-flight would otherwise pop
    // every already-completed dot at once instead of just the next one.
    if (!stageAnimationReady.current) {
      stageAnimationReady.current = true;
      return;
    }
    if (reduced) return;
    const newlyDone = STAGES.filter((stage) => reached.has(stage) && !previous.has(stage));
    if (newlyDone.length === 0) return;
    loadAnime().then(({ animate }) => {
      for (const stage of newlyDone) {
        const node = dotRefs.current[stage];
        if (node)
          animate(node, { scale: [1, 1.3, 1], duration: STAGE_POP_DURATION, ease: 'outQuad' });
      }
    });
    // `reached` is a fresh Set every render; `reachedKey` is its stable
    // fingerprint, so the effect only re-runs when membership actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reachedKey, reduced]);

  const cancel = async () => {
    setCancelling(true);
    try {
      await api.post(`/v1/generation-jobs/${jobId}/cancel`);
      setConfirmCancel(false);
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-5">
        {current.output_url ? (
          // The result is the first thing an author checks against the phone
          // they will publish from, so the frames are offered here rather than
          // one page later.
          <DevicePreview src={current.output_url} title={t('title')} />
        ) : (
          <Poster src={null} alt={t('waiting')} aspect="video" className="border border-border">
            <div className="absolute inset-0 grid place-items-center">
              <p aria-live="polite" className="tabular flex items-center gap-2 text-sm text-muted">
                <IconSparkle className="size-4 text-amber" />
                {tJob('progress', { percent: current.progress })}
              </p>
            </div>
          </Poster>
        )}

        <div>
          <div
            role="progressbar"
            aria-valuenow={current.progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t('title')}
            className="h-1.5 overflow-hidden rounded-full bg-track"
          >
            <div
              ref={barRef}
              className="h-full rounded-full bg-primary"
              style={{ width: `${initialProgress}%` }}
            />
          </div>

          <ol className="mt-4 flex flex-wrap gap-x-6 gap-y-3">
            {STAGES.map((stage, index) => {
              const done = reached.has(stage);
              const active = index === activeIndex && !finished;
              return (
                <li
                  key={stage}
                  aria-current={active ? 'step' : undefined}
                  className={cn(
                    'flex items-center gap-1.5 text-xs',
                    done ? 'text-success' : active ? 'text-text' : 'text-muted',
                  )}
                >
                  <span
                    ref={(node) => {
                      dotRefs.current[stage] = node;
                    }}
                    className={cn(
                      'grid size-4 place-items-center rounded-full border',
                      done
                        ? 'border-success bg-success/15'
                        : active
                          ? 'border-primary'
                          : 'border-border',
                    )}
                  >
                    {done ? <IconCheck className="size-2.5" /> : null}
                  </span>
                  {t(
                    `stage${stage.charAt(0).toUpperCase()}${stage.slice(1)}` as
                      | 'stageQueued'
                      | 'stagePlanning'
                      | 'stageSafety'
                      | 'stageGenerating'
                      | 'stageSound'
                      | 'stageQuality'
                      | 'stageDone',
                  )}
                </li>
              );
            })}
          </ol>
        </div>

        {reconnecting ? (
          <p role="status" className="text-xs text-amber">
            {tJob('reconnecting')}
          </p>
        ) : null}

        {current.status === 'failed' ? (
          <ErrorNotice
            title={current.failure_message ?? t('failedTitle')}
            detail={`${t('failedHint')}${current.failure_code ? ` · ${tJob('errorCode', { code: current.failure_code })}` : ''}`}
            action={
              <Button size="sm" variant="secondary" onClick={() => router.push('/create')}>
                {tJob('retry')}
              </Button>
            }
          />
        ) : null}

        {current.status === 'cancelled' ? (
          <ErrorNotice title={t('cancelledTitle')} detail={t('failedHint')} />
        ) : null}

        {/* Keeps the tail of the page clear of the fixed bar below. */}
        <div aria-hidden="true" className="safe-mb h-16 lg:hidden" />

        {/* One row, two homes: pinned above the home indicator on a phone,
            inline under the timeline once there is room for it. */}
        <div className="safe-b fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center gap-3 border-t border-border bg-surface px-4 py-3 lg:static lg:border-0 lg:bg-transparent lg:px-0 lg:py-0">
          {current.status === 'succeeded' && current.draft_id ? (
            <Button onClick={() => router.push(`/publish/${current.draft_id}`)}>
              {tJob('publish')}
            </Button>
          ) : null}
          {!finished ? (
            <Button
              variant="secondary"
              onClick={() => setConfirmCancel(true)}
              disabled={current.cancel_requested}
            >
              {tJob('cancel')}
            </Button>
          ) : null}
          <Button variant="ghost" onClick={() => router.push('/create')}>
            {t('backToCreate')}
          </Button>
        </div>
      </div>

      <aside className="flex flex-col gap-4">
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <div className="flex items-center justify-between gap-3">
            <Badge
              tone={
                current.status === 'succeeded'
                  ? 'success'
                  : current.status === 'failed'
                    ? 'danger'
                    : 'primary'
              }
            >
              {tJob(current.status)}
            </Badge>
            {current.route ? (
              <span
                className="truncate text-[11px] text-muted"
                title={current.route.model_or_workflow}
              >
                {current.route.model_or_workflow}
              </span>
            ) : null}
          </div>

          <dl className="tabular mt-4 flex flex-col gap-2 text-xs">
            <Row
              label={t('creditsReserved', { count: formatCount(current.reserved_credits, locale) })}
            />
            {current.actual_credits !== null && current.actual_credits !== undefined ? (
              <Row
                label={t('creditsSettled', { count: formatCount(current.actual_credits, locale) })}
              />
            ) : null}
            {current.status === 'failed' || current.status === 'cancelled' ? (
              <Row
                label={t('creditsRefunded', {
                  count: formatCount(current.reserved_credits, locale),
                })}
              />
            ) : null}
          </dl>
        </div>

        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('eventLog')}</h2>
          {events.length === 0 ? (
            <p className="mt-3 flex items-center gap-2 text-xs text-muted">
              <IconClock className="size-3.5" />
              {t('waiting')}
            </p>
          ) : (
            <ol className="mt-3 flex flex-col gap-3">
              {events.map((event) => (
                <li key={event.sequence} className="flex gap-3 text-xs">
                  <span className="tabular mt-0.5 shrink-0 text-muted">
                    {event.created_at ? formatDateTime(event.created_at, locale) : ''}
                  </span>
                  <span className="min-w-0">{event.message}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </aside>

      <Dialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title={tJob('cancel')}
        description={t('cancelConfirm')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" loading={cancelling} onClick={() => void cancel()}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('failedHint')}</p>
      </Dialog>
    </div>
  );
}

function Row({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2">
      <dt className="sr-only">{label}</dt>
      <dd className="text-muted">{label}</dd>
    </div>
  );
}
