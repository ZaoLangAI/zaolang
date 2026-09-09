'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { IconCheck } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { Draft, GenerationJob } from '@/lib/api/types';
import { isCharacterCompletionJob } from '@/lib/characters';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

/** A job in one of these statuses never becomes (or stays) a version-history
 * record — see the `GenerationVersionHistory` doc comment below. */
const DEAD_JOB_STATUSES = new Set(['failed', 'cancelled', 'expired']);

/**
 * The image and video studios' shared version history — every generation
 * job filed under the same `Draft`, in the order they were made. Flat and
 * chronological, not a tree: branching from an older version just means
 * picking it back up as the next iteration's reference
 * (`InlineImageResult`'s "基于此图继续微调" / `InlineVideoResult`'s "基于此
 * 视频继续创作"), so there is nothing to render as a graph — the lineage
 * graph (`zaolang-lineage-graph`) is a different, published-`Work` concept.
 *
 * Takes the draft's full job list as a prop rather than fetching it itself —
 * `ImageGenerationStudio`/`VideoGenerationStudio` own that (`knownJobsById`),
 * seeded once from `GET /v1/generation-jobs?draft_id=` and additively kept
 * up to date with every job it has seen since (submitted, streamed, or
 * selected from this very list), so a job never disappears here just
 * because it stopped being the one currently shown.
 *
 * A "补全侧面/背面" completion job (`isCharacterCompletionJob`) is filtered
 * out entirely, never counted or rendered as a version of its own — it
 * supplements whichever front-view version it was submitted for instead
 * (merged into that version's own gallery by `InlineImageResult`, see
 * `lib/characters.ts#findCompletionJobFor`). Never true for a video job
 * (video has no character-completion concept), so this is a no-op there.
 *
 * A video version's thumbnail has no backend-generated cover frame to show —
 * a `<video>` element with a `#t=0.1` media-fragment `src` and no controls
 * paints that moment without ever starting playback, standing in for a
 * still image the same way `job.output_url` alone does for an image job.
 *
 * A failed/cancelled/expired attempt leaves no trace here at all — it is
 * filtered out entirely, not just excluded from the version count. Its
 * failure is already visible where it happened (`InlineImageResult`'s error
 * notice and retry button); this strip only ever shows a *record* worth
 * picking back up, which a dead attempt never is.
 *
 * `appliedJobId` is the draft's currently applied version (preview /
 * publish output) — distinct from the locally selected preview (`activeJob`).
 * Apply / hide write through `POST /v1/drafts/{id}/applied-version` and
 * `DELETE /v1/drafts/{id}/versions/{jobId}`; hide is a history tombstone,
 * not a hard delete of the job or its credits.
 */
export function GenerationVersionHistory({
  jobs,
  activeJob,
  appliedJobId,
  draftId,
  onSelect,
  onAppliedChange,
  onHidden,
}: {
  jobs: GenerationJob[];
  activeJob: GenerationJob | null;
  appliedJobId?: string | null;
  draftId?: string | null;
  onSelect: (job: GenerationJob) => void;
  onAppliedChange?: (draft: Draft) => void;
  onHidden?: (jobId: string) => void;
}) {
  const t = useTranslations('remixPage');
  const tJob = useTranslations('job');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const [hidingJob, setHidingJob] = useState<GenerationJob | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [hiding, setHiding] = useState(false);

  const versions = useMemo(() => {
    const byId = new Map<string, GenerationJob>();
    for (const job of jobs) byId.set(job.id, job);
    const sorted = [...byId.values()]
      // A dead attempt (failed/cancelled/expired) never becomes a record —
      // see the doc comment above. Anything still in flight (queued/running/
      // awaiting_input) stays, since it may yet succeed and earn its slot.
      .filter((job) => !DEAD_JOB_STATUSES.has(job.status))
      // A completion job is a supplement, not a version — see the doc
      // comment above.
      .filter((job) => !isCharacterCompletionJob(job))
      .sort(
        (left, right) =>
          new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
      );
    // The version number is a count of *successful* generations, not the raw
    // chronological position — the still-in-flight entry above only claims
    // the *next* number provisionally; it is not "spent" unless that job
    // actually succeeds. Written as a `reduce` (rather than a loop mutating
    // an outer counter) so nothing captured outside the callback is
    // reassigned across iterations.
    return sorted.reduce<{ job: GenerationJob; versionNumber: number }[]>((entries, job) => {
      const succeededCount = entries.filter((entry) => entry.job.status === 'succeeded').length;
      return [...entries, { job, versionNumber: succeededCount + 1 }];
    }, []);
  }, [jobs]);

  const applyVersion = async (job: GenerationJob) => {
    if (!draftId) return;
    setApplyingId(job.id);
    try {
      const draft = await api.post<Draft>(`/v1/drafts/${draftId}/applied-version`, {
        job_id: job.id,
      });
      onAppliedChange?.(draft);
      notify(t('applyVersionDone'), 'success');
    } catch (caught) {
      notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
    } finally {
      setApplyingId(null);
    }
  };

  const hideVersion = async () => {
    if (!draftId || !hidingJob) return;
    setHiding(true);
    try {
      await api.delete(`/v1/drafts/${draftId}/versions/${hidingJob.id}`);
      onHidden?.(hidingJob.id);
      notify(t('hideVersionDone'), 'success');
      setHidingJob(null);
    } catch (caught) {
      notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
    } finally {
      setHiding(false);
    }
  };

  if (versions.length === 0) return null;

  return (
    <section aria-labelledby="generation-history-heading" className="flex flex-col gap-2">
      <h2 id="generation-history-heading" className="text-sm font-semibold">
        {t('generationHistory', { count: versions.length })}
      </h2>
      <ol className="flex gap-3 overflow-x-auto pb-1">
        {versions.map(({ job, versionNumber }) => {
          const selected = job.id === activeJob?.id;
          const applied = job.id === appliedJobId;
          const thumbnail = job.output_url ?? null;
          const canManage = Boolean(draftId) && job.status === 'succeeded';
          return (
            <li key={job.id} className="w-28 shrink-0">
              <button
                type="button"
                onClick={() => onSelect(job)}
                aria-current={selected ? 'true' : undefined}
                title={job.prompt ?? undefined}
                className={cn(
                  'block w-full overflow-hidden rounded-[var(--radius-sm)] border text-left transition-colors',
                  'focus-visible:outline-2',
                  selected
                    ? 'border-primary ring-1 ring-primary'
                    : 'border-border hover:border-border-strong',
                )}
              >
                <div className="relative aspect-square bg-surface-soft">
                  {thumbnail && job.output_media_type === 'video' ? (
                    // No poster image on hand for a video job (there is no
                    // backend-generated cover frame) — a `#t=0.1` media
                    // fragment forces the browser to seek to (and paint) that
                    // moment without ever starting playback, which is all a
                    // static thumbnail needs.
                    <video
                      src={`${thumbnail}#t=0.1`}
                      muted
                      playsInline
                      preload="metadata"
                      className="absolute inset-0 size-full object-cover"
                    />
                  ) : thumbnail ? (
                    <Image src={thumbnail} alt="" fill sizes="112px" className="object-cover" />
                  ) : (
                    <div className="absolute inset-0 grid place-items-center">
                      <VersionStatusIcon status={job.status} />
                    </div>
                  )}
                  <span
                    className={cn(
                      'absolute left-1 top-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      'bg-surface-raised/90 text-muted',
                    )}
                  >
                    V{versionNumber}
                  </span>
                  {applied ? (
                    <span
                      className={cn(
                        'absolute right-1 top-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                        'bg-primary text-on-primary',
                      )}
                    >
                      {t('appliedVersion')}
                    </span>
                  ) : null}
                </div>
                <p className="truncate bg-surface px-1.5 py-1 text-[10px] text-muted">
                  {job.status === 'succeeded'
                    ? formatRelative(job.created_at, locale)
                    : tJob(job.status)}
                </p>
              </button>
              {canManage ? (
                <div className="mt-1 flex flex-col gap-0.5">
                  {!applied ? (
                    <button
                      type="button"
                      disabled={applyingId === job.id}
                      onClick={() => void applyVersion(job)}
                      className="text-left text-[10px] text-muted hover:text-text focus-visible:outline-2"
                    >
                      {applyingId === job.id ? tActions('saving') : t('applyVersion')}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setHidingJob(job)}
                    className="text-left text-[10px] text-muted hover:text-danger focus-visible:outline-2"
                  >
                    {t('hideVersion')}
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      <ConfirmDialog
        open={hidingJob !== null}
        onClose={() => !hiding && setHidingJob(null)}
        title={t('hideVersionTitle')}
        description={t('hideVersionBody')}
        confirmLabel={t('hideVersionConfirm')}
        cancelLabel={tActions('cancel')}
        busy={hiding}
        onConfirm={() => void hideVersion()}
      />
    </section>
  );
}

// Only ever rendered for a `succeeded` job with no thumbnail yet or a job
// still in flight — `DEAD_JOB_STATUSES` filters everything else out of
// `versions` before this ever gets a chance to render for them.
function VersionStatusIcon({ status }: { status: string }) {
  if (status === 'succeeded') return <IconCheck className="size-4 text-success" />;
  return <Spinner className="size-4 text-muted" />;
}
