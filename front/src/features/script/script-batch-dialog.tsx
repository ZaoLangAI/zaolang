'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { formatCount } from '@/lib/format';
import { FALLBACK_VOICES, unionVoices, useGenerationModels } from '@/lib/use-generation-models';

import type { BatchKind, BatchParams, BatchQuote } from './use-script-batch';
import {
  DEFAULT_AUDIO_PARAMS,
  DEFAULT_CHARACTER_PARAMS,
  DEFAULT_SCENE_PARAMS,
  DEFAULT_VIDEO_PARAMS,
  quoteForBatch,
} from './use-script-batch';

const TIERS: BatchParams['qualityTier'][] = ['preview', 'standard', 'cinematic'];
const VIDEO_DURATIONS = [4, 6, 8, 10, 12, 15];
const CHARACTER_ASPECTS = ['3:4', '2:3', '9:16'];
const SCENE_ASPECTS = ['16:9', '4:3', '21:9'];
const VIDEO_ASPECTS = ['9:16', '16:9', '3:4', '4:3'];
const RESOLUTIONS: BatchParams['resolution'][] = ['720p', '1080p', '2K'];

const ZERO_QUOTE: BatchQuote = {
  unitCredits: 0,
  totalCredits: 0,
  count: 0,
  availableCredits: 0,
  sufficient: true,
};

function defaultsFor(kind: BatchKind): BatchParams {
  if (kind === 'characters') return DEFAULT_CHARACTER_PARAMS;
  if (kind === 'scenes') return DEFAULT_SCENE_PARAMS;
  if (kind === 'audio') return DEFAULT_AUDIO_PARAMS;
  return DEFAULT_VIDEO_PARAMS;
}

function aspectsFor(kind: BatchKind): string[] {
  if (kind === 'characters') return CHARACTER_ASPECTS;
  if (kind === 'scenes') return SCENE_ASPECTS;
  return VIDEO_ASPECTS;
}

export function ScriptBatchDialog({
  kind,
  labels,
  skipLinked,
  skipUnreferenced,
  existingRefByLabel,
  onClose,
  onConfirm,
}: {
  kind: BatchKind | null;
  labels: string[];
  skipLinked: number;
  skipUnreferenced: number;
  /** Script character name → library card id. Those rows default to skip. */
  existingRefByLabel?: Record<string, string>;
  onClose: () => void;
  onConfirm: (params: BatchParams, quote: BatchQuote, skippedLabels: string[]) => void;
}) {
  const t = useTranslations('scriptStudio');
  const tCredits = useTranslations('credits');
  // Reuses the audio studio's own voice-picker copy rather than duplicating
  // it under `scriptStudio` — same "音色"/"选择生成语音使用的音色。" strings.
  const tAudio = useTranslations('remixPage');
  const locale = useLocale() as Locale;
  const [params, setParams] = useState<BatchParams>(() => defaultsFor(kind ?? 'characters'));
  const [quote, setQuote] = useState<BatchQuote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [quoting, setQuoting] = useState(false);
  const [openKind, setOpenKind] = useState<BatchKind | null>(kind);
  const [extraSkip, setExtraSkip] = useState<Set<string>>(() => new Set());

  const existingNames = useMemo(
    () => new Set(Object.keys(existingRefByLabel ?? {})),
    [existingRefByLabel],
  );
  const skipped = useMemo(() => {
    const next = new Set(existingNames);
    for (const name of extraSkip) next.add(name);
    return next;
  }, [existingNames, extraSkip]);
  const generateCount =
    kind === 'characters' ? labels.filter((label) => !skipped.has(label)).length : labels.length;
  const skipExistingCount = kind === 'characters' ? existingNames.size : 0;

  // Reset during render so the quote effect never sees the previous
  // kind's params (scene 16:9 / duration 0 leaking into a video quote).
  if (kind !== openKind) {
    setOpenKind(kind);
    setQuote(null);
    setQuoteFailed(false);
    setExtraSkip(new Set());
    if (kind) setParams(defaultsFor(kind));
  }

  // Each new quote request is marked during render (same pattern as the kind
  // reset above) so the effect below only fetches.
  const [quotedFor, setQuotedFor] = useState<{
    kind: BatchKind | null;
    params: BatchParams;
    generateCount: number;
  } | null>(null);
  if (
    quotedFor?.kind !== kind ||
    quotedFor.params !== params ||
    quotedFor.generateCount !== generateCount
  ) {
    setQuotedFor({ kind, params, generateCount });
    if (kind && generateCount === 0) {
      setQuote(ZERO_QUOTE);
      setQuoteFailed(false);
      setQuoting(false);
    } else if (kind) {
      setQuoting(true);
    }
  }

  useEffect(() => {
    if (!kind || generateCount === 0) return;
    let cancelled = false;
    void quoteForBatch(kind, params, generateCount)
      .then((next) => {
        if (cancelled) return;
        setQuote(next);
        setQuoteFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setQuote(null);
        setQuoteFailed(true);
      })
      .finally(() => {
        if (!cancelled) setQuoting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, generateCount, params]);

  // "自动选择" (no forced model in the batch runner) — the same union
  // fallback `AudioGenerationStudio` shows before picking a model.
  const audioModelOptions = useGenerationModels('audio_generation');
  const audioVoices = useMemo(() => {
    const union = unionVoices(audioModelOptions);
    return union.length > 0 ? union : [...FALLBACK_VOICES];
  }, [audioModelOptions]);

  // Adjusted during render rather than in an effect: it only reacts to state
  // this component already has, and settles after one pass.
  if (
    kind === 'audio' &&
    audioVoices.length > 0 &&
    (!params.voice || !audioVoices.includes(params.voice))
  ) {
    setParams((current) => ({ ...current, voice: audioVoices[0] }));
  }

  if (!kind) return null;

  const title =
    kind === 'characters'
      ? t('batchConfirmCharactersTitle')
      : kind === 'scenes'
        ? t('batchConfirmScenesTitle')
        : kind === 'audio'
          ? t('batchConfirmAudioTitle')
          : t('batchConfirmVideosTitle');

  const canSubmit = Boolean(quote?.sufficient) && !quoting && !quoteFailed && labels.length > 0;

  const toggleSkip = (label: string) => {
    if (existingNames.has(label)) return;
    setExtraSkip((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      description={
        quote
          ? t('batchConfirmDescription', {
              count: generateCount,
              credits: formatCount(quote.totalCredits, locale),
            })
          : undefined
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('batchCancel')}
          </Button>
          <Button
            disabled={!canSubmit}
            loading={quoting}
            onClick={() => {
              if (!quote) return;
              onConfirm(params, quote, [...skipped]);
            }}
          >
            {t('batchConfirm')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {generateCount > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label={t('batchQuality')}
              value={params.qualityTier}
              options={TIERS.map((value) => ({ value, label: t(`batchTier.${value}`) }))}
              onChange={(event) =>
                setParams((current) => ({
                  ...current,
                  qualityTier: event.target.value as BatchParams['qualityTier'],
                }))
              }
            />
            {kind !== 'audio' ? (
              <Select
                label={t('batchAspect')}
                value={params.aspectRatio}
                options={aspectsFor(kind).map((value) => ({ value, label: value }))}
                onChange={(event) =>
                  setParams((current) => ({ ...current, aspectRatio: event.target.value }))
                }
              />
            ) : (
              <Select
                label={tAudio('voice')}
                hint={tAudio('voiceHint')}
                value={params.voice ?? audioVoices[0]}
                options={audioVoices.map((value) => ({ value, label: value }))}
                onChange={(event) =>
                  setParams((current) => ({ ...current, voice: event.target.value }))
                }
              />
            )}
            {kind === 'videos' ? (
              <>
                <Select
                  label={t('batchDuration')}
                  value={String(params.durationSeconds)}
                  options={VIDEO_DURATIONS.map((value) => ({
                    value: String(value),
                    label: t('batchDurationSeconds', { count: value }),
                  }))}
                  onChange={(event) =>
                    setParams((current) => ({
                      ...current,
                      durationSeconds: Number(event.target.value),
                    }))
                  }
                />
                <Select
                  label={t('batchResolution')}
                  value={params.resolution}
                  options={RESOLUTIONS.map((value) => ({ value, label: value }))}
                  onChange={(event) =>
                    setParams((current) => ({
                      ...current,
                      resolution: event.target.value as BatchParams['resolution'],
                    }))
                  }
                />
              </>
            ) : null}
          </div>
        ) : null}

        {quoting && !quote ? (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Spinner />
            {t('loading')}
          </div>
        ) : null}
        {quoteFailed ? <ErrorNotice title={t('batchQuoteFailed')} /> : null}
        {quote && !quote.sufficient ? <ErrorNotice title={t('batchInsufficient')} /> : null}
        {quote && generateCount > 0 ? (
          <p className="text-sm text-amber">
            {tCredits('amount', { count: formatCount(quote.totalCredits, locale) })}
          </p>
        ) : null}

        {skipLinked > 0 ? (
          <p className="text-xs text-muted">{t('batchConfirmSkip', { count: skipLinked })}</p>
        ) : null}
        {skipExistingCount > 0 ? (
          <p className="text-xs text-muted">
            {t('batchConfirmSkipExisting', { count: skipExistingCount })}
          </p>
        ) : null}
        {skipUnreferenced > 0 ? (
          <p className="text-xs text-muted">
            {t('batchConfirmSkipUnreferenced', { count: skipUnreferenced })}
          </p>
        ) : null}

        <div>
          <p className="mb-1.5 text-xs font-medium text-muted">
            {kind === 'characters' ? t('batchSkipGenerate') : t('batchWillGenerate')}
          </p>
          <ul className="max-h-40 overflow-y-auto rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-sm">
            {kind === 'characters'
              ? labels.map((label) => {
                  const existing = existingNames.has(label);
                  const checked = skipped.has(label);
                  return (
                    <li key={label} className="py-0.5">
                      <label className="flex cursor-pointer items-center gap-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={existing}
                          onChange={() => toggleSkip(label)}
                          className="size-3.5 shrink-0 accent-current"
                        />
                        <span className="min-w-0 truncate">{label}</span>
                        {existing ? (
                          <span className="shrink-0 text-xs text-muted">
                            {t('batchExistingInLibrary')}
                          </span>
                        ) : null}
                      </label>
                    </li>
                  );
                })
              : labels.map((label) => (
                  <li key={label} className="truncate py-0.5">
                    {label}
                  </li>
                ))}
          </ul>
        </div>
      </div>
    </Dialog>
  );
}
