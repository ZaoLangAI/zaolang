'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useEffectEvent, useState } from 'react';

import { ChipGroup } from '@/components/studio/asset-preset-fields';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { cn } from '@/lib/cn';
import {
  MATRIX_AXES,
  MAX_MATRIX_AXIS_VALUES,
  MAX_MATRIX_CELLS,
  type MatrixAxis,
  matrixCellCount,
  matrixCellProgress,
  matrixGrid,
} from '@/features/image-assets/matrix';
import {
  keysOf,
  SCENE_LIGHTINGS,
  SCENE_PERIODS,
  SCENE_STATES,
  SCENE_WEATHERS,
} from '@/features/image-assets/vocabulary';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { GenerationJob, SceneMatrixCell, SceneMatrixResponse } from '@/lib/api/types';

const POLL_MS = 3000;

const TABLES: Record<MatrixAxis, Record<string, { labelKey: string }>> = {
  lighting: SCENE_LIGHTINGS,
  weather: SCENE_WEATHERS,
  state: SCENE_STATES,
  period: SCENE_PERIODS,
};

type Axes = Record<MatrixAxis, string[]>;
const EMPTY_AXES: Axes = { lighting: [], weather: [], state: [], period: [] };

/**
 * 批量变体: pick values per axis, see every combination with what the card
 * already holds, and the exact total — then submit one image job per new
 * combination (`POST /v1/scenes/{id}/variants:matrix`, P2-5). Combinations
 * with an approved master plate, or with candidates waiting, are skipped.
 * Each finished image files itself under the variant matching its presets.
 */
export function SceneMatrixDialog({
  sceneId,
  open,
  onClose,
  onSubmitted,
  onProgress,
}: {
  sceneId: string;
  open: boolean;
  onClose: () => void;
  /** Called after a submit queued at least one job. */
  onSubmitted?: () => void;
  /** A submitted cell's job finished — refresh the card so its image shows. */
  onProgress?: () => void;
}) {
  const t = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const [axes, setAxes] = useState<Axes>(EMPTY_AXES);
  // The last plan, with the picks it was made for: a slow dry run must never
  // be shown (or submitted against) for picks that have changed since.
  const [plan, setPlan] = useState<{ key: string; response: SceneMatrixResponse } | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SceneMatrixResponse | null>(null);
  const [page, setPage] = useState(0);
  // Submitted cells' job statuses, polled until every one has finished (§9.3).
  const [statuses, setStatuses] = useState<Record<string, GenerationJob['status']>>({});
  const url = `/v1/scenes/${sceneId}/variants:matrix`;
  const count = matrixCellCount(axes);
  const tooMany = count > MAX_MATRIX_CELLS;
  const planned = count > 0 && !tooMany;
  const axesKey = JSON.stringify(axes);

  useEffect(() => {
    if (!open || !planned) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .post<SceneMatrixResponse>(url, { axes, dry_run: true })
        .then((response) => {
          if (cancelled) return;
          setPlan({ key: JSON.stringify(axes), response });
          setPlanError(null);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setPlanError(err instanceof ApiError ? err.message : t('genericError'));
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, planned, axes, url, t]);

  const jobIds = (result?.cells ?? []).flatMap((cell) => (cell.job_id ? [cell.job_id] : []));
  const unfinished = jobIds.filter((id) => {
    const progress = matrixCellProgress(statuses[id]);
    return progress !== 'done' && progress !== 'failed';
  });
  const unfinishedKey = unfinished.join(',');
  const onCellFinished = useEffectEvent(() => onProgress?.());
  useEffect(() => {
    if (!unfinishedKey) return;
    let stopped = false;
    const tick = async () => {
      const latest = await Promise.all(
        unfinishedKey
          .split(',')
          .map((id) => api.get<GenerationJob>(`/v1/generation-jobs/${id}`).catch(() => null)),
      );
      if (stopped) return;
      const finished = latest.filter((job) => {
        const progress = job ? matrixCellProgress(job.status) : 'queued';
        return progress === 'done' || progress === 'failed';
      });
      setStatuses((current) => {
        const next = { ...current };
        for (const job of latest) if (job) next[job.id] = job.status;
        return next;
      });
      if (finished.length > 0) onCellFinished();
    };
    const id = window.setInterval(() => void tick(), POLL_MS);
    void tick();
    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [unfinishedKey]);
  const doneCount = jobIds.filter((id) => matrixCellProgress(statuses[id]) === 'done').length;

  // Reopening after every submitted cell has finished starts from the card
  // as it is now: the last submit's badges would be stale, and a fresh dry
  // run shows the new variants as 已有 (or lets a failed cell be retried).
  // While jobs are still running the progress view stays.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open && result && unfinished.length === 0) {
      setResult(null);
      setPlan(null);
      setStatuses({});
      setSubmitError(null);
      setPage(0);
    }
  }

  const current = planned && plan?.key === axesKey ? plan.response : null;
  const shown = result ?? current;
  const pending = planned && !result && !current && !planError;
  const newCount = shown?.cells.filter((cell) => cell.status === 'new').length ?? 0;
  const grid = shown ? matrixGrid(axes, shown.cells) : null;
  const shownPage = grid?.pages[Math.min(page, grid.pages.length - 1)];

  const toggle = (axis: MatrixAxis, value: string) => {
    setResult(null);
    setPage(0);
    setAxes((current) => ({
      ...current,
      [axis]: current[axis].includes(value)
        ? current[axis].filter((item) => item !== value)
        : [...current[axis], value],
    }));
  };

  const valueLabel = (axis: MatrixAxis, value: string) => {
    const entry = TABLES[axis][value];
    return entry ? tPresets(`presets.${entry.labelKey}`) : value;
  };
  const presetsLabel = (presets: Partial<Record<MatrixAxis, string | null>>) =>
    MATRIX_AXES.filter((axis) => presets[axis])
      .map((axis) => valueLabel(axis, presets[axis] as string))
      .join(' · ');

  const progressBadge = (progress: ReturnType<typeof matrixCellProgress>) => {
    const tone = {
      queued: 'neutral',
      running: 'amber',
      waiting: 'amber',
      done: 'success',
      failed: 'danger',
    } as const;
    return <Badge tone={tone[progress]}>{t(`matrixProgress.${progress}`)}</Badge>;
  };

  const cellBadge = (cell: SceneMatrixCell) =>
    cell.error ? (
      <Badge tone="danger">{t('matrixCellFailed')}</Badge>
    ) : cell.job_id ? (
      progressBadge(matrixCellProgress(statuses[cell.job_id]))
    ) : (
      <Badge tone={cell.status === 'new' ? 'primary' : 'neutral'}>
        {t(`matrixStatus.${cell.status}`)}
      </Badge>
    );

  const submit = async () => {
    setBusy(true);
    setSubmitError(null);
    try {
      const response = await api.post<SceneMatrixResponse>(
        url,
        { axes, dry_run: false },
        { idempotencyKey: newIdempotencyKey() },
      );
      setResult(response);
      if (response.submitted > 0) onSubmitted?.();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : t('genericError'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('matrixTitle')}
      description={t('matrixHint')}
      size="lg"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t(result ? 'close' : 'cancel')}
          </Button>
          {result ? null : (
            <Button
              loading={busy}
              disabled={!planned || !shown || newCount === 0 || !shown.sufficient}
              onClick={() => void submit()}
            >
              {t('matrixSubmit', { count: newCount, credits: shown?.total_credits ?? 0 })}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {MATRIX_AXES.map((axis) => (
          <ChipGroup
            key={axis}
            label={tPresets(`presets.axis${axis[0]?.toUpperCase()}${axis.slice(1)}`)}
            options={keysOf(TABLES[axis]).map((value) => ({
              value,
              label: tPresets(`presets.${TABLES[axis][value]?.labelKey}`),
            }))}
            selected={axes[axis]}
            onToggle={(value) => toggle(axis, value)}
            max={MAX_MATRIX_AXIS_VALUES}
          />
        ))}

        <p className="text-xs text-muted" role="status">
          {count === 0
            ? t('matrixEmpty')
            : tooMany
              ? t('matrixTooMany', { count, max: MAX_MATRIX_CELLS })
              : pending
                ? t('matrixPlanning', { count })
                : t('matrixCount', { count })}
        </p>

        {planError && planned ? <ErrorNotice title={planError} /> : null}
        {submitError ? <ErrorNotice title={submitError} /> : null}

        {shown ? (
          <>
            {grid && grid.pages.length > 1 ? (
              <div role="tablist" className="flex flex-wrap gap-1.5">
                {grid.pages.map((candidate, index) => (
                  <button
                    key={presetsLabel(candidate.presets)}
                    type="button"
                    role="tab"
                    aria-selected={candidate === shownPage}
                    onClick={() => setPage(index)}
                    className={cn(
                      'rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs transition-colors',
                      candidate === shownPage
                        ? 'border-primary bg-primary/10 text-text'
                        : 'border-border text-muted hover:text-text',
                    )}
                  >
                    {presetsLabel(candidate.presets)}
                  </button>
                ))}
              </div>
            ) : null}
            {grid && shownPage ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  {grid.colAxis ? (
                    <thead>
                      <tr>
                        <th className="p-1.5" />
                        {grid.colValues.map((value) => (
                          <th
                            key={value}
                            scope="col"
                            className="p-1.5 text-left font-medium text-muted"
                          >
                            {valueLabel(grid.colAxis as MatrixAxis, value)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                  ) : null}
                  <tbody>
                    {shownPage.rows.map((row, rowIndex) => {
                      const rowValue = grid.rowValues[rowIndex] ?? '';
                      return (
                        <tr key={rowValue} className="border-t border-border">
                          <th scope="row" className="p-1.5 text-left font-medium text-muted">
                            {valueLabel(grid.rowAxis, rowValue)}
                          </th>
                          {row.map((cell, colIndex) => (
                            <td key={grid.colValues[colIndex] ?? colIndex} className="p-1.5">
                              {cell ? cellBadge(cell) : <span className="text-muted">—</span>}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
            {result ? (
              <p className="text-xs text-muted" role="status">
                {t('matrixSubmitted', { count: result.submitted })}{' '}
                {t('matrixProgressSummary', { done: doneCount, total: jobIds.length })}
              </p>
            ) : !shown.sufficient && newCount > 0 ? (
              <p className="text-xs text-danger" role="status">
                {t(shown.within_spend_limit ? 'matrixInsufficient' : 'matrixOverSpendLimit', {
                  credits: shown.total_credits,
                  available: shown.available_credits,
                })}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </Dialog>
  );
}
