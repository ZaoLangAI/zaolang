'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useEffectEvent, useRef, useState } from 'react';

import { ChipGroup } from '@/features/image-assets/chip-group';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import {
  DEFAULT_FILL_EXPRESSIONS,
  FILL_SLOTS,
  type FillStep,
  fillStep,
} from '@/features/image-assets/fill';
import {
  CHARACTER_EXPRESSIONS,
  type CharacterExpression,
  keysOf,
  MAX_CHARACTER_EXPRESSIONS,
} from '@/features/image-assets/vocabulary';
import { Link } from '@/i18n/navigation';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { AssetVariant, GenerationJob, LookFillResponse, LookFillSlot } from '@/lib/api/types';

const POLL_MS = 3000;
const FINISHED: GenerationJob['status'][] = ['succeeded', 'failed', 'cancelled', 'expired'];

/**
 * 补齐缺失 (P2-4): the look's standard set — identity portrait, front sheet,
 * side / back views, one expression grid — with what is missing priced as a
 * whole, then generated wave by wave (`POST …/looks/{id}:fill`). Each wave is
 * one job; when it succeeds the card is refreshed and the next wave starts on
 * its own (decided 2026-10-02: no per-wave confirmation). Slots that only
 * have candidates are left alone — approve or delete those first.
 */
export function LookFillDialog({
  characterId,
  look,
  open,
  onClose,
  onProgress,
}: {
  characterId: string;
  look: AssetVariant;
  open: boolean;
  onClose: () => void;
  /** A wave finished — refresh the card so its new images show. */
  onProgress: () => void;
}) {
  const t = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const url = `/v1/characters/${characterId}/looks/${look.id}:fill`;
  const [unselected, setUnselected] = useState<LookFillSlot[]>([]);
  const [expressions, setExpressions] = useState<CharacterExpression[]>([
    ...DEFAULT_FILL_EXPRESSIONS,
  ]);
  const [plan, setPlan] = useState<{ key: string; response: LookFillResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<FillStep | null>(null);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [busy, setBusy] = useState(false);
  const lastSlots = useRef<LookFillSlot[] | null>(null);

  const body = {
    slots: FILL_SLOTS.filter((slot) => !unselected.includes(slot)),
    expressions,
  };
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    if (!open || step) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .post<LookFillResponse>(url, { ...JSON.parse(bodyKey), dry_run: true })
        .then((response) => {
          if (cancelled) return;
          setPlan({ key: bodyKey, response });
          setError(null);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof ApiError ? err.message : t('genericError'));
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, step, url, bodyKey, t]);

  const submitWave = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<LookFillResponse>(
        url,
        { ...body, dry_run: false },
        { idempotencyKey: newIdempotencyKey() },
      );
      const next = fillStep(response, lastSlots.current);
      if (next.kind === 'running') lastSlots.current = next.slots;
      setJob(null);
      setStep(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('genericError'));
    } finally {
      setBusy(false);
    }
  };

  // Poll the running wave; on success refresh the card and start the next.
  const onWaveSucceeded = useEffectEvent(() => {
    onProgress();
    void submitWave();
  });
  const runningJobId = step?.kind === 'running' ? step.jobId : null;
  useEffect(() => {
    if (!runningJobId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const latest = await api.get<GenerationJob>(`/v1/generation-jobs/${runningJobId}`);
        if (stopped) return;
        setJob(latest);
        if (FINISHED.includes(latest.status)) {
          stopped = true;
          window.clearInterval(id);
          if (latest.status === 'succeeded') onWaveSucceeded();
        }
      } catch {
        // A dropped poll is retried on the next tick.
      }
    };
    const id = window.setInterval(() => void tick(), POLL_MS);
    void tick();
    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [runningJobId]);

  const current = plan?.key === bodyKey ? plan.response : null;
  const slotLabel = (slot: LookFillSlot) => t(`fillSlot.${slot}`);
  const failed = job && ['failed', 'cancelled', 'expired'].includes(job.status);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('fillTitle', { name: look.name })}
      description={t('fillHint')}
      size="lg"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t(step ? 'close' : 'cancel')}
          </Button>
          {!step ? (
            <Button
              loading={busy}
              disabled={!current || current.lines.length === 0 || !current.sufficient}
              onClick={() => void submitWave()}
            >
              {t('fillSubmit', { credits: current?.total_credits ?? 0 })}
            </Button>
          ) : failed || step.kind === 'stuck' ? (
            <Button
              loading={busy}
              onClick={() => {
                lastSlots.current = null;
                void submitWave();
              }}
            >
              {t('fillRetry')}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? <ErrorNotice title={error} /> : null}

        {!step && current ? (
          <>
            <ul className="flex flex-col gap-1.5">
              {FILL_SLOTS.map((slot) => {
                const status = current.gaps[slot];
                const selectable = status === 'missing';
                return (
                  <li
                    key={slot}
                    className="flex items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-sm"
                  >
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        disabled={!selectable}
                        checked={selectable && !unselected.includes(slot)}
                        onChange={(event) =>
                          setUnselected((list) =>
                            event.target.checked
                              ? list.filter((item) => item !== slot)
                              : [...list, slot],
                          )
                        }
                      />
                      {slotLabel(slot)}
                    </label>
                    <Badge
                      tone={
                        status === 'missing'
                          ? 'primary'
                          : status === 'candidate'
                            ? 'amber'
                            : 'neutral'
                      }
                    >
                      {t(`fillStatus.${status}`)}
                    </Badge>
                  </li>
                );
              })}
            </ul>
            {current.gaps.expressions === 'missing' && !unselected.includes('expressions') ? (
              <ChipGroup
                label={t('fillExpressions')}
                options={keysOf(CHARACTER_EXPRESSIONS).map((key) => ({
                  value: key,
                  label: tPresets(`presets.${CHARACTER_EXPRESSIONS[key].labelKey}`),
                }))}
                selected={expressions}
                onToggle={(value) =>
                  setExpressions((list) =>
                    list.includes(value)
                      ? list.length > 1
                        ? list.filter((item) => item !== value)
                        : list
                      : [...list, value],
                  )
                }
                max={MAX_CHARACTER_EXPRESSIONS}
              />
            ) : null}
            <p className="text-xs text-muted" role="status">
              {current.lines.length === 0
                ? t('fillNothing')
                : current.sufficient
                  ? t('fillQuote', { steps: current.lines.length, credits: current.total_credits })
                  : t('fillInsufficient', {
                      credits: current.total_credits,
                      available: current.available_credits,
                    })}
            </p>
          </>
        ) : null}

        {step?.kind === 'running' ? (
          <div className="flex flex-col gap-2 text-sm" role="status">
            <p>
              {t('fillRunning', { slots: step.slots.map(slotLabel).join('、') })}
              {' · '}
              {failed ? t('fillWaveFailed') : t('fillWaveWaiting')}
            </p>
            <Link href={`/jobs/${step.jobId}`} className="text-xs text-muted hover:text-text">
              {t('fillOpenJob')}
            </Link>
          </div>
        ) : null}
        {step?.kind === 'done' ? (
          <p className="text-sm" role="status">
            {t('fillDone')}
          </p>
        ) : null}
        {step?.kind === 'stuck' ? (
          <ErrorNotice title={t('fillStuck', { slots: step.slots.map(slotLabel).join('、') })} />
        ) : null}
      </div>
    </Dialog>
  );
}
