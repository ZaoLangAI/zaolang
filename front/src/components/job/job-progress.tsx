'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { LiveThinking } from '@/components/ai/thinking-disclosure';
import { useSession } from '@/components/auth/session-provider';
import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { PromoteJobDialog } from '@/components/job/promote-job-dialog';
import {
  CHARACTER_VIEW_LABEL_KEY,
  STAGES,
  stageLabelKey,
  type Stage,
} from '@/components/job/job-stages';
import { jobStageState } from '@/components/job/job-stage-state';
import { DevicePreview } from '@/components/media/device-preview';
import { DownloadAssetButton } from '@/components/media/download-asset-button';
import { OutputGallery } from '@/components/media/output-gallery';
import { SaveCoverAsSkillDialog } from '@/components/studio/save-cover-as-skill-dialog';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { IconCheck, IconClock, IconCopy, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { createCutFromJob } from '@/features/editor/from-job';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { Draft, GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount, formatDateTime } from '@/lib/format';
import { loadAnime, useReducedMotion } from '@/lib/motion';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import { useJobStream } from '@/lib/use-job-stream';
import { useResource } from '@/lib/use-resource';

const PROGRESS_DURATION = 650;
const STAGE_POP_DURATION = 420;

export function JobProgress({ jobId, initial }: { jobId: string; initial: GenerationJob }) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tEditor = useTranslations('editor');
  const tActions = useTranslations('actions');
  const tCharacters = useTranslations('characters');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { notify } = useToast();
  const { user } = useSession();

  const { job, events, connected, reconnecting, liveThinking, applyJob } = useJobStream(
    jobId,
    initial,
  );
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [savingCoverSkillOpen, setSavingCoverSkillOpen] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  /**
   * One key for this failed job's retry, not one per click — a network
   * failure leaves the server's outcome unknown, and re-minting a key would
   * let a second click double-reserve credits for the same retry.
   */
  const pendingRetryKey = useRef<string | null>(null);

  const current = job ?? initial;
  const { reached, displayStage, finished, awaitingInput, reachedKey } = jobStageState(
    current.status,
    events,
  );
  const latestEvent = events[events.length - 1];
  const showAwaitingPanel = awaitingInput && !current.cancel_requested;

  // A multi-view `CHARACTER` job loops back through `asset_planning` once
  // per remaining view (see `execute_asset_output_advance`) — one `node_id
  // === 'asset_planning'` event fires per view attempt, in `character_views`
  // order, so counting them tells us which view is currently in flight
  // without guessing from the (loop-restarting) stage dots above.
  const characterViews = current.character_views ?? null;
  const isMultiViewCharacter =
    current.asset_kind === 'character' && (characterViews?.length ?? 0) > 1;
  const assetPlanningEntries = isMultiViewCharacter
    ? events.filter((event) => event.node_id === 'asset_planning').length
    : 0;
  const currentViewIndex = Math.min(
    Math.max(assetPlanningEntries - 1, 0),
    (characterViews?.length ?? 1) - 1,
  );

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

  // A new job (see `POST .../retry`'s own doc comment on why it's a new job
  // rather than reopening this one), so success navigates to it rather than
  // patching `current` in place — this page's SSE stream is scoped to `jobId`.
  const retry = async () => {
    setRetrying(true);
    try {
      pendingRetryKey.current ??= newIdempotencyKey();
      const next = await api.post<GenerationJob>(`/v1/generation-jobs/${jobId}/retry`, undefined, {
        idempotencyKey: pendingRetryKey.current,
      });
      pendingRetryKey.current = null;
      router.push(`/jobs/${next.id}`);
    } catch (error) {
      // A changed request under the same key would 409 forever; only that
      // case forces a fresh key on the next attempt.
      if (isApiError(error) && error.code === 'IDEMPOTENCY_CONFLICT') {
        pendingRetryKey.current = null;
      }
      notify(isApiError(error) ? error.message : t('cancelFailed'), 'error');
    } finally {
      setRetrying(false);
    }
  };

  const enterEditor = async () => {
    setOpeningEditor(true);
    // Opened synchronously (before the await below) so the browser attributes
    // it to this click, not to the async response that follows — opening
    // asynchronously here would get blocked as an unrequested popup in most
    // browsers.
    const tab = window.open('', '_blank', 'noopener,noreferrer');
    try {
      const cut = await createCutFromJob(jobId);
      const draftQuery = current.draft_id ? `?draftId=${encodeURIComponent(current.draft_id)}` : '';
      const path = `/studio-editor/${cut.id}${draftQuery}`;
      if (tab) tab.location.href = `/${locale}${path}`;
      else router.push(path);
    } catch (error) {
      tab?.close();
      // Flag-off is the only 404 that should degrade to publish. A missing
      // or foreign `link_episode_id` is also NOT_FOUND — sending that to
      // `/publish` hid the real error behind a different page.
      if (
        isApiError(error) &&
        error.isNotFound &&
        error.message.includes('暂未开放') &&
        current.draft_id
      ) {
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

  // Reads the flag straight off `/v1/auth/me` rather than probing
  // `GET /drama-series` — that probe could succeed while `web_editor_enabled`
  // itself was off (the series list has no flag check of its own), flashing
  // a button that then 404s on `create_cut_from_job`. `undefined` (session
  // not loaded yet) fails open, same as the old probe's own "don't hide on
  // a transient error" stance.
  const showEnterEditor = canEnterEditor && (user?.features.web_editor ?? true);

  // A cover-kind job's output is a single, standalone image with no roster
  // to maintain (unlike a character/scene) — see `CreationSkillCategory.
  // COVER_ASSET`'s own note on why it has no dedicated CRUD surface, just
  // this `POST /v1/skills` call with the job's own output as the thumbnail.
  const canSaveCoverSkill =
    current.status === 'succeeded' &&
    current.asset_kind === 'cover' &&
    Boolean(current.output_asset_id);

  // A preview-tier success is a cheap, fast sample — this is the only route
  // from it to a full-priced standard/cinematic render (`POST .../promote`
  // reserves that as its own new job, see the dialog's own doc comment).
  const canPromote = current.status === 'succeeded' && current.quality_tier === 'preview';
  const canDownload =
    current.status === 'succeeded' &&
    current.output_media_type === 'video' &&
    Boolean(current.output_asset_id);

  // Fetched only once there's a draft worth asking about, so the "去发布"
  // button can tell "already submitted, wait" and "already live" apart from
  // a fresh, unsubmitted draft — a plain "发布" label on all three used to
  // invite a second, `Conflict`-refused submit on a draft already pending.
  const draftResource = useResource<Draft>(
    current.status === 'succeeded' && current.draft_id ? `/v1/drafts/${current.draft_id}` : null,
  );
  const draftPublishStatus = draftResource.data?.publish_status ?? null;
  const publishedWorkId = draftResource.data?.published_work_id ?? null;

  const refreshOutputSrc = useCallback(async () => {
    if (current.output_asset_id) return refreshAssetUrl(current.output_asset_id);
    return refreshJobOutputUrl(jobId);
  }, [current.output_asset_id, jobId]);

  const hasMultipleOutputs = (current.output_urls?.length ?? 0) > 1;
  // Labels line up with `output_urls`/`output_asset_ids` only for a
  // multi-view character job — both lists are recorded in the same
  // front → side → back order (see `execute_asset_output_advance`).
  const outputLabels =
    characterViews && characterViews.length === current.output_urls?.length
      ? characterViews.map((view) => tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewFront'))
      : undefined;

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
          {hasMultipleOutputs && current.output_urls ? (
            <OutputGallery
              urls={current.output_urls}
              assetIds={current.output_asset_ids}
              mediaType={current.output_media_type ?? 'image'}
              title={t('title')}
              labels={outputLabels}
              itemLabel={(index, total) => t('outputItemLabel', { index, total })}
            />
          ) : current.output_url ? (
            current.output_media_type === 'audio' ? (
              <audio
                src={current.output_url}
                controls
                className="w-full rounded-[var(--radius-md)] border border-border p-4"
              />
            ) : (
              <DevicePreview
                src={current.output_url}
                title={t('title')}
                mediaType={current.output_media_type === 'image' ? 'image' : 'video'}
                refreshSrc={refreshOutputSrc}
              />
            )
          ) : showAwaitingPanel ? (
            <AwaitingInputPanel key={jobId} jobId={jobId} />
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
                  <p className="text-sm text-text">
                    {t(stageLabelKey(displayStage, current.operation))}
                  </p>
                  {latestEvent?.message ? (
                    <p className="max-w-md text-sm text-muted">{latestEvent.message}</p>
                  ) : null}
                  {!finished ? (
                    <LiveThinking
                      thinking={liveThinking.text}
                      label={t('thinkingLive')}
                      className="max-h-32 overflow-y-auto"
                    />
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
              {STAGES.map((stage) => {
                const done = awaitingInput && stage === 'planning' ? false : reached.has(stage);
                const active = awaitingInput
                  ? stage === 'planning'
                  : stage === displayStage && !finished;
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
                    {t(stageLabelKey(stage, current.operation))}
                  </li>
                );
              })}
            </ol>

            {isMultiViewCharacter && characterViews ? (
              <ol className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <li className="text-muted">
                  {t('characterViewsTitle', {
                    current: currentViewIndex + 1,
                    total: characterViews.length,
                  })}
                </li>
                {characterViews.map((view, index) => {
                  const viewDone = index < currentViewIndex || current.status === 'succeeded';
                  const viewActive = index === currentViewIndex && !finished && !viewDone;
                  return (
                    <li
                      key={view}
                      className={cn(
                        'flex items-center gap-1 rounded-full border px-2 py-0.5',
                        viewDone
                          ? 'border-success text-success'
                          : viewActive
                            ? 'border-primary text-text'
                            : 'border-border text-muted',
                      )}
                    >
                      {viewDone ? <IconCheck className="size-2.5" /> : null}
                      {tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewFront')}
                    </li>
                  );
                })}
              </ol>
            ) : null}
          </div>

          {current.status === 'failed' ? (
            <ErrorNotice
              title={current.failure_message ?? t('failedTitle')}
              detail={`${t('failedHint')}${current.failure_code ? ` · ${tJob('errorCode', { code: current.failure_code })}` : ''}`}
              action={
                <Button
                  size="sm"
                  variant="secondary"
                  loading={retrying}
                  onClick={() => void retry()}
                >
                  {tJob('retry')}
                </Button>
              }
            />
          ) : null}

          {current.status === 'cancelled' ? (
            <ErrorNotice
              title={t('cancelledTitle')}
              detail={t('failedHint')}
              action={
                <Button
                  size="sm"
                  variant="secondary"
                  loading={retrying}
                  onClick={() => void retry()}
                >
                  {tJob('retry')}
                </Button>
              }
            />
          ) : null}

          {showAwaitingPanel && (hasMultipleOutputs || current.output_url) ? (
            <AwaitingInputPanel key={jobId} jobId={jobId} />
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
            {canDownload && current.output_asset_id ? (
              <DownloadAssetButton
                assetId={current.output_asset_id}
                label={t('download')}
                failedMessage={t('downloadFailed')}
                size="md"
              />
            ) : null}
            {current.status === 'succeeded' && current.draft_id ? (
              publishedWorkId ? (
                <Button
                  variant={showEnterEditor ? 'secondary' : 'primary'}
                  onClick={() => router.push(`/work/${publishedWorkId}`)}
                >
                  {t('openWork')}
                </Button>
              ) : draftPublishStatus === 'pending' ? (
                <Button variant="secondary" disabled>
                  {t('publishPending')}
                </Button>
              ) : (
                <Button
                  variant={showEnterEditor ? 'secondary' : 'primary'}
                  onClick={() => router.push(`/publish/${current.draft_id}`)}
                >
                  {tJob('publish')}
                </Button>
              )
            ) : null}
            {canSaveCoverSkill ? (
              <Button variant="secondary" onClick={() => setSavingCoverSkillOpen(true)}>
                {t('saveCoverSkill')}
              </Button>
            ) : null}
            {canPromote ? (
              <Button variant="secondary" onClick={() => setPromoteOpen(true)}>
                {t('promote')}
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
                      key={event.sequence ?? `event-${index}`}
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

      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title={tJob('cancel')}
        description={t('cancelConfirm')}
        confirmLabel={tActions('confirm')}
        cancelLabel={tActions('cancel')}
        busy={cancelling}
        onConfirm={() => void cancel()}
      >
        <p className="text-sm text-muted">{t('failedHint')}</p>
      </ConfirmDialog>

      <SaveCoverAsSkillDialog
        open={savingCoverSkillOpen}
        onClose={() => setSavingCoverSkillOpen(false)}
        outputAssetId={current.output_asset_id}
      />

      <PromoteJobDialog
        open={promoteOpen}
        onClose={() => setPromoteOpen(false)}
        job={current}
        onPromoted={(promoted) => router.push(`/jobs/${promoted.id}`)}
      />
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
