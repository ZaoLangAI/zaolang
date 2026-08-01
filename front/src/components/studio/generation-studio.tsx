'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SourceMaterialRail } from '@/components/studio/source-material-rail';
import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { IconClock, IconSparkle, IconVolume, IconVolumeOff } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Poster } from '@/components/media/poster';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { GenerationJob, Quote, ReusableParams, WorkDetail } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';

type Tier = 'preview' | 'standard' | 'cinematic';
type Operation = 'text_to_video' | 'image_to_video' | 'video_to_video' | 'text_to_image';

const ASPECTS = ['16:9', '9:16', '1:1'] as const;
const DURATIONS = [8, 12, 20] as const;

export interface StudioSource {
  work: WorkDetail;
  params: ReusableParams;
}

/**
 * The generation form shared by `/create/new` and `/remix/[workId]`.
 *
 * Both routes submit the same job with the same pricing rules; the only real
 * difference is whether a source work seeds the materials and the prompt. One
 * component means the remix path cannot silently drift from the create path.
 */
export function GenerationStudio({
  operation: initialOperation,
  source,
}: {
  operation: Operation;
  source?: StudioSource;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { requireAuth, status: sessionStatus } = useSession();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? '');
  const [aspect, setAspect] = useState<string>('16:9');
  const [duration, setDuration] = useState<number>(8);
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<Tier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);

  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const operation: Operation =
    initialOperation === 'text_to_video' && (source || uploads.length > 0)
      ? 'image_to_video'
      : initialOperation;

  // Re-quote whenever the priced inputs change. Debounced because the tier and
  // duration controls are adjacent and users sweep across them.
  const quoteKey = `${operation}:${tier}:${duration}`;
  const latestQuote = useRef(0);
  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    const ticket = ++latestQuote.current;
    const timer = setTimeout(() => {
      void api
        .post<Quote>('/v1/generation-jobs/quote', {
          operation,
          quality_tier: tier,
          duration_seconds: duration,
        })
        .then((body) => {
          if (ticket !== latestQuote.current) return;
          setQuote(body);
          setQuoteFailed(false);
        })
        .catch(() => {
          if (ticket !== latestQuote.current) return;
          setQuoteFailed(true);
        });
    }, 250);
    return () => clearTimeout(timer);
    // `quoteKey` collapses the three priced inputs into one dependency.
  }, [quoteKey, operation, tier, duration, sessionStatus]);

  const tierOptions = useMemo(
    () => [
      { value: 'preview' as const, label: t('tierPreview'), hint: t('tierPreviewDesc') },
      { value: 'standard' as const, label: t('tierStandard'), hint: t('tierStandardDesc') },
      { value: 'cinematic' as const, label: t('tierCinematic'), hint: t('tierCinematicDesc') },
    ],
    [t],
  );

  const referenceAssetIds = [...uploads.map((asset) => asset.id)];
  const canSubmit =
    prompt.trim().length > 0 && rightsConfirmed && !submitting && (quote?.sufficient ?? true);

  const submit = () =>
    requireAuth({
      label: t('submit'),
      run: async () => {
        setSubmitting(true);
        setError(null);
        try {
          const job = await api.post<GenerationJob>(
            '/v1/generation-jobs',
            {
              operation,
              quality_tier: tier,
              source_work_id: source?.work.id,
              params: {
                prompt: prompt.trim(),
                aspect_ratio: aspect,
                duration_seconds: duration,
                reference_asset_ids: referenceAssetIds,
                extra: { sound },
              },
              max_credits: quote?.credits,
            },
            // One key per intent: a retried submit must not create a second job.
            { idempotencyKey: newIdempotencyKey() },
          );
          router.push(`/jobs/${job.id}`);
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
          setSubmitting(false);
        }
      },
    });

  return (
    <div className="grid gap-5 lg:grid-cols-[184px_minmax(0,1fr)_340px]">
      <SourceMaterialRail
        source={source}
        uploads={uploads}
        onUploaded={(asset) => setUploads((current) => [...current, asset])}
        onRemove={(id) => setUploads((current) => current.filter((asset) => asset.id !== id))}
      />

      <div className="flex flex-col gap-4">
        <Poster
          src={source?.work.current_version?.cover_url ?? source?.work.cover_url}
          alt={source?.work.title ?? t('promptLabel')}
          aspect="video"
          className="border border-border"
        />

        {source ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-1.5 text-success">
              <IconSparkle className="size-4" />
              {t('keepAttribution')}
            </span>
            <span className="text-muted">
              {source.work.author.display_name}
              {source.work.license ? ` · ${source.work.license.attribution_text}` : ''}
            </span>
          </div>
        ) : null}

        <div className="flex gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
          <IconSparkle className="size-5 shrink-0 text-amber" />
          <div>
            <p className="text-sm font-medium">{t('directHint')}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{t('directHintBody')}</p>
          </div>
        </div>
      </div>

      <aside className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">{t('howToGenerate')}</h2>

        <div>
          <TextArea
            label={t('promptLabel')}
            placeholder={t('promptPlaceholder')}
            value={prompt}
            maxLength={600}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <p className="tabular mt-1 text-right text-[11px] text-muted">{prompt.length}/600</p>
        </div>

        <OptionGroup
          label={t('aspect')}
          value={aspect}
          onChange={setAspect}
          options={ASPECTS.map((value) => ({ value, label: value }))}
        />

        <OptionGroup
          label={t('duration')}
          value={duration}
          onChange={setDuration}
          options={DURATIONS.map((value) => ({
            value,
            label: t('durationSeconds', { count: value }),
          }))}
        />

        <OptionGroup
          label={t('sound')}
          value={sound ? 'on' : 'off'}
          onChange={(value) => setSound(value === 'on')}
          columns={2}
          options={[
            { value: 'off', label: t('soundOff'), icon: <IconVolumeOff className="size-4" /> },
            { value: 'on', label: t('soundAmbient'), icon: <IconVolume className="size-4" /> },
          ]}
        />

        <OptionGroup
          label={t('quality')}
          value={tier}
          onChange={setTier}
          options={tierOptions.map((option) => ({
            ...option,
            trailing: quote && option.value === tier ? `${quote.credits}+` : undefined,
          }))}
        />

        <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
          <input
            type="checkbox"
            checked={rightsConfirmed}
            onChange={(event) => setRightsConfirmed(event.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
          />
          {t('rightsConfirm')}
        </label>

        {quoteFailed ? (
          <ErrorNotice title={t('quoteFailed')} />
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
            <div>
              <p className="flex items-center gap-1.5 text-xs">
                <IconClock className="size-3.5 text-muted" />
                {quote ? formatDuration(quote.estimated_seconds) : '—'}
              </p>
              <p className="mt-0.5 text-[11px] text-muted">{t('estimateHint')}</p>
            </div>
            <p className="tabular shrink-0 text-sm font-semibold text-amber">
              {quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—'}
            </p>
          </div>
        )}

        {quote && !quote.sufficient ? (
          <ErrorNotice
            title={tCredits('insufficient')}
            action={
              <Button size="sm" variant="secondary" onClick={() => router.push('/billing')}>
                {tCredits('manage')}
              </Button>
            }
          />
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}

        <Button
          size="lg"
          onClick={submit}
          disabled={!canSubmit}
          loading={submitting}
          icon={<IconSparkle className="size-5" />}
        >
          {submitting ? t('submitting') : t('submit')}
        </Button>
      </aside>
    </div>
  );
}
