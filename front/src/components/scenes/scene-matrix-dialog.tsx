'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { ChipGroup } from '@/components/studio/asset-preset-fields';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import {
  MATRIX_AXES,
  MAX_MATRIX_AXIS_VALUES,
  MAX_MATRIX_CELLS,
  type MatrixAxis,
  matrixCellCount,
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
import type { SceneMatrixCell, SceneMatrixResponse } from '@/lib/api/types';

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
}: {
  sceneId: string;
  open: boolean;
  onClose: () => void;
  /** Called after a submit queued at least one job. */
  onSubmitted?: () => void;
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

  const current = planned && plan?.key === axesKey ? plan.response : null;
  const shown = result ?? current;
  const pending = planned && !result && !current && !planError;
  const newCount = shown?.cells.filter((cell) => cell.status === 'new').length ?? 0;

  const toggle = (axis: MatrixAxis, value: string) => {
    setResult(null);
    setAxes((current) => ({
      ...current,
      [axis]: current[axis].includes(value)
        ? current[axis].filter((item) => item !== value)
        : [...current[axis], value],
    }));
  };

  const cellLabel = (cell: SceneMatrixCell) =>
    MATRIX_AXES.filter((axis) => cell.presets[axis])
      .map((axis) => {
        const entry = TABLES[axis][cell.presets[axis] as string];
        return entry ? tPresets(`presets.${entry.labelKey}`) : cell.presets[axis];
      })
      .join(' · ');

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
            <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {shown.cells.map((cell) => (
                <li
                  key={JSON.stringify(cell.presets)}
                  className="flex items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs"
                >
                  <span className="truncate text-text">{cellLabel(cell)}</span>
                  {cell.error ? (
                    <Badge tone="danger">{t('matrixCellFailed')}</Badge>
                  ) : cell.job_id ? (
                    <Badge tone="success">{t('matrixCellQueued')}</Badge>
                  ) : (
                    <Badge tone={cell.status === 'new' ? 'primary' : 'neutral'}>
                      {t(`matrixStatus.${cell.status}`)}
                    </Badge>
                  )}
                </li>
              ))}
            </ul>
            {result ? (
              <p className="text-xs text-muted" role="status">
                {t('matrixSubmitted', { count: result.submitted })}
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
