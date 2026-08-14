'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { DevicePreview } from '@/components/media/device-preview';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconCheck, IconClock, IconCopy, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { checkEditorAvailable } from '@/features/editor/api';
import { createCutFromJob } from '@/features/editor/from-job';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount, formatDateTime } from '@/lib/format';
import { loadAnime, useReducedMotion } from '@/lib/motion';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import { useJobStream } from '@/lib/use-job-stream';

const PROGRESS_DURATION = 650;
const STAGE_POP_DURATION = 420;

/** Ordered stages aligned with the generation pipeline, mapped from event types. */
const STAGES = ['queued', 'safety', 'planning', 'generating', 'sound', 'quality', 'done'] as const;
type Stage = (typeof STAGES)[number];

const STAGE_LABEL = {
  queued: 'stageQueued',
  safety: 'stageSafety',
  planning: 'stagePlanning',
  generating: 'stageGenerating',
  sound: 'stageSound',
  quality: 'stageQuality',
  done: 'stageDone',
} as const satisfies Record<Stage, string>;

const STAGE_FOR_EVENT: Record<string, Stage> = {
  created: 'queued',
  queued: 'queued',
  safety: 'safety',
  safety_checked: 'safety',
  planning: 'planning',
  planned: 'planning',
  intent_routing: 'planning',
  routing: 'generating',
  routed: 'generating',
  generating: 'generating',
  provider_started: 'generating',
  progress: 'generating',
  awaiting_input: 'generating',
  audio: 'sound',
  sound: 'sound',
  quality_check: 'quality',
  quality_checked: 'quality',
  settled: 'done',
  succeeded: 'done',
};

export function JobProgress({ jobId, initial }: { jobId: string; initial: GenerationJob }) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tEditor = useTranslations('editor');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { notify } = useToast();

  const { job, events, connected, reconnecting, applyJob } = useJobStream(jobId, initial);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [editorAvailable, setEditorAvailable] = useState<boolean | null>(null);

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
  const latestEvent = events[events.length - 1];
  const displayStage: Stage =
    finished && current.status !== 'succeeded'
      ? ([...STAGES].reverse().find((stage) => reached.has(stage)) ?? 'queued')
      : (STAGES[activeIndex] ?? 'done');

  const reduced = useReducedMotion();
  // Frozen at mount so React never rewrites `style.width` on a later render —
  // once mounted, the bar is driven purely by the imperative effect below, or
  // this snapshot would race with anime and always win, snapping the value
  // before the animation had a chance to run. State (not a ref) because the
  // value is read during render, for the very first paint's inline style.
  const [initialProgress] = useState(current.progress);
  const barRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLOListElement>(null);
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
  }, [current.progress, reduced, current.output_url]);

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

  useEffect(() => {
    const node = logRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const cancel = async () => {
    setCancelling(true);
    try {
      const latest = await api.post<GenerationJob>(`/v1/generation-jobs/${jobId}/cancel`);
      applyJob(latest);
      setConfirmCancel(false);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('cancelFailed'), 'error');
    } finally {
      setCancelling(false);
    }
  };

  const enterEditor = async () => {
    setOpeningEditor(true);
    try {
      const cut = await createCutFromJob(jobId);
      const draftQuery = current.draft_id ? `?draftId=${encodeURIComponent(current.draft_id)}` : '';
      router.push(`/create/drama/${cut.id}${draftQuery}`);
    } catch (error) {
      if (isApiError(error) && error.isNotFound && current.draft_id) {
        router.push(`/publish/${current.draft_id}`);
        return;
      }
      notify(isApiError(error) ? error.message : tEditor('commandFailed'), 'error');
    } finally {
      setOpeningEditor(false);
    }
  };

  const canEnterEditor =
    current.status === 'succeeded' &&
    (current.operation === 'text_to_video' ||
      current.operation === 'image_to_video' ||
      current.operation === 'video_to_video');

  useEffect(() => {
    if (!canEnterEditor) return;
    let cancelled = false;
    void checkEditorAvailable().then((available) => {
      if (!cancelled) setEditorAvailable(available);
    });
    return () => {
      cancelled = true;
    };
  }, [canEnterEditor]);

  const showEnterEditor = canEnterEditor && editorAvailable !== false;

  const refreshOutputSrc = useCallback(async () => {
    if (current.output_asset_id) return refreshAssetUrl(current.output_asset_id);
    return refreshJobOutputUrl(jobId);
  }, [current.output_asset_id, jobId]);

  const progressBar = (
    <div
      role="progressbar"
      aria-valuenow={current.progress}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={t('title')}
      className="h-1.5 overflow-hidden bg-track"
    >
      <div
        ref={barRef}
        className="h-full rounded-full bg-primary"
        style={{ width: `${initialProgress}%` }}
      />
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{t('title')}</h1>
          <Badge tone={statusTone(current.status)}>{tJob(current.status)}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="tabular min-w-0 truncate">{current.id}</span>
          <CopyJobId
            id={current.id}
            label={t('copyId')}
            copiedLabel={t('idCopied')}
            onCopied={() => notify(t('idCopied'), 'success')}
          />
          {reconnecting ? (
            <span role="status" className="text-amber">
              {tJob('reconnecting')}
            </span>
          ) : connected && !finished ? (
            <span role="status" className="text-success">
              {t('liveUpdating')}
            </span>
          ) : null}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-5">
          {current.output_url ? (
            current.output_media_type === 'image' ? (
              // Native img: job output URLs are short-lived object signatures.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={current.output_url}
                alt={t('title')}
                className="w-full rounded-[var(--radius-md)] border border-border object-contain"
              />
            ) : current.output_media_type === 'audio' ? (
              <audio
                src={current.output_url}
                controls
                className="w-full rounded-[var(--radius-md)] border border-border p-4"
              />
            ) : (
              <DevicePreview
                src={current.output_url}
                title={t('title')}
                refreshSrc={refreshOutputSrc}
              />
            )
          ) : (
            <div className="relative aspect-video overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
              <div className="absolute inset-0 grid place-items-center px-6">
                <div className="flex flex-col items-center gap-2 text-center">
                  <IconSparkle
                    className={cn('size-5 text-amber', !reduced && !finished && 'animate-pulse')}
                  />
                  <p
                    aria-live="polite"
                    className="tabular text-4xl font-semibold tracking-tight text-text"
                  >
                    {current.progress}%
                  </p>
                  <p className="text-sm text-text">{t(STAGE_LABEL[displayStage])}</p>
                  {latestEvent?.message ? (
                    <p className="max-w-md text-sm text-muted">{latestEvent.message}</p>
                  ) : null}
                </div>
              </div>
              <div className="absolute inset-x-0 bottom-0">{progressBar}</div>
            </div>
          )}

          <div>
            {current.output_url ? (
              <div className="overflow-hidden rounded-full">{progressBar}</div>
            ) : null}

            <ol
              className={cn('flex flex-wrap gap-x-6 gap-y-3', current.output_url ? 'mt-4' : null)}
            >
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
                    {t(STAGE_LABEL[stage])}
                  </li>
                );
              })}
            </ol>
          </div>

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

          {current.status === 'awaiting_input' && !current.cancel_requested ? (
            <AwaitingInputPanel jobId={jobId} />
          ) : null}
          {current.cancel_requested && !finished ? (
            <p role="status" className="text-sm text-muted">
              {t('cancellingHint')}
            </p>
          ) : null}

          {/* Keeps the tail of the page clear of the fixed bar below. */}
          <div aria-hidden="true" className="safe-mb h-16 lg:hidden" />

          {/* One row, two homes: pinned above the home indicator on a phone,
            inline under the timeline once there is room for it. */}
          <div className="safe-b fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center gap-3 border-t border-border bg-surface px-4 py-3 lg:static lg:border-0 lg:bg-transparent lg:px-0 lg:py-0">
            {showEnterEditor ? (
              <Button onClick={() => void enterEditor()} loading={openingEditor}>
                {tJob('enterEditor')}
              </Button>
            ) : null}
            {current.status === 'succeeded' && current.draft_id ? (
              <Button
                variant={showEnterEditor ? 'secondary' : 'primary'}
                onClick={() => router.push(`/publish/${current.draft_id}`)}
              >
                {tJob('publish')}
              </Button>
            ) : null}
            {!finished ? (
              <Button
                variant="secondary"
                onClick={() => setConfirmCancel(true)}
                disabled={current.cancel_requested}
              >
                {current.cancel_requested ? tJob('cancelRequested') : tJob('cancel')}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => router.push('/create')}>
              {t('backToCreate')}
            </Button>
          </div>
        </div>

        <aside className="flex flex-col gap-4">
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            {current.route ? (
              <p
                className="truncate text-[11px] text-muted"
                title={current.route.model_or_workflow}
              >
                {current.route.model_or_workflow}
              </p>
            ) : null}

            <dl className={cn('tabular flex flex-col gap-2 text-xs', current.route && 'mt-4')}>
              <Row
                label={t('creditsReserved', {
                  count: formatCount(current.reserved_credits, locale),
                })}
              />
              {current.actual_credits !== null && current.actual_credits !== undefined ? (
                <Row
                  label={t('creditsSettled', {
                    count: formatCount(current.actual_credits, locale),
                  })}
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
              <ol ref={logRef} className="mt-3 flex max-h-80 flex-col gap-3 overflow-y-auto">
                {events.map((event, index) => {
                  const latest = index === events.length - 1;
                  return (
                    <li
                      key={event.sequence}
                      className={cn(
                        'flex gap-3 rounded-[var(--radius-sm)] px-1.5 py-1 text-xs',
                        latest ? 'bg-surface-soft text-text' : null,
                      )}
                    >
                      <span className="tabular mt-0.5 shrink-0 text-muted">
                        {event.created_at ? formatDateTime(event.created_at, locale) : ''}
                      </span>
                      <span className="min-w-0">{event.message}</span>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </aside>
      </div>

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

function statusTone(status: string): BadgeTone {
  if (status === 'succeeded') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled' || status === 'expired') return 'amber';
  return 'primary';
}

function CopyJobId({
  id,
  label,
  copiedLabel,
  onCopied,
}: {
  id: string;
  label: string;
  copiedLabel: string;
  onCopied: () => void;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      aria-label={copied ? copiedLabel : label}
      onClick={() => {
        void navigator.clipboard.writeText(id).then(() => {
          setCopied(true);
          onCopied();
          window.setTimeout(() => setCopied(false), 1600);
        });
      }}
      className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-[var(--radius-sm)] text-muted hover:text-text focus-visible:outline-2"
    >
      {copied ? <IconCheck className="size-3.5 text-success" /> : <IconCopy className="size-3.5" />}
    </button>
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
