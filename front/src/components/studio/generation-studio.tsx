'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { SourceMaterialRail } from '@/components/studio/source-material-rail';
import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { IconClock, IconGear, IconSparkle, IconVolume, IconVolumeOff } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { DevicePreview } from '@/components/media/device-preview';
import { Poster } from '@/components/media/poster';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { ReusableParams, WorkDetail } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import { DEFAULT_DEVICE_ID } from '@/lib/devices';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useMinWidth } from '@/lib/use-media-query';

type Tier = 'preview' | 'standard' | 'cinematic';
type Operation = 'text_to_video' | 'image_to_video' | 'video_to_video' | 'text_to_image';

const ASPECTS = ['16:9', '9:16', '1:1'] as const;
const DURATIONS = [8, 12, 20] as const;
const PORTRAIT_ASPECT = '9:16';
const PROMPT_MAX_LENGTH = 600;

export interface StudioSource {
  work: WorkDetail;
  params: ReusableParams;
}

/**
 * The generation form shared by `/create/new` and `/remix/[workId]`.
 *
 * Both routes submit the same job with the same pricing rules; the only real
 * difference is whether a source work seeds the materials and the prompt. One
 * component means the remix path cannot silently drift from the create path,
 * and the parts a differently shaped shell would still have to repeat live in
 * `use-generation-submit`.
 *
 * The three columns collapse rather than shrink below `lg`: the preview leads,
 * the materials scroll sideways under it, and the parameters move into a bottom
 * sheet with the estimate pinned above the thumb.
 */
export function GenerationStudio({
  operation: initialOperation,
  source,
  reference,
  initialPrompt,
}: {
  operation: Operation;
  /** A licensed remix source. Submitted as `source_work_id`. */
  source?: StudioSource;
  /**
   * A work the idea came from, carried over from the discover feed.
   *
   * Never submitted as `source_work_id` and never added to the reference
   * assets: doing either would fabricate a lineage edge that no author
   * authorised, which is exactly what `assert_remixable` exists to prevent.
   */
  reference?: WorkDetail;
  initialPrompt?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;
  const router = useRouter();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [aspect, setAspect] = useState<string>('16:9');
  const [duration, setDuration] = useState<number>(8);
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<Tier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [paramsRequested, setParamsRequested] = useState(false);

  const operation: Operation =
    initialOperation === 'text_to_video' && (source || uploads.length > 0)
      ? 'image_to_video'
      : initialOperation;

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation, qualityTier: tier, durationSeconds: duration },
    { label: t('submit') },
  );

  // The sheet is the narrow layout's third column. Derived rather than closed
  // in an effect: at `lg` those controls are on the page, so "open" is not a
  // state the wide layout can be in at all.
  const isDesktop = useMinWidth('lg');
  const paramsOpen = paramsRequested && !isDesktop;

  const tierOptions = useMemo(
    () => [
      { value: 'preview' as const, label: t('tierPreview'), hint: t('tierPreviewDesc') },
      { value: 'standard' as const, label: t('tierStandard'), hint: t('tierStandardDesc') },
      { value: 'cinematic' as const, label: t('tierCinematic'), hint: t('tierCinematicDesc') },
    ],
    [t],
  );

  const canSubmit =
    prompt.trim().length > 0 && rightsConfirmed && !submitting && (quote?.sufficient ?? true);

  const runSubmit = () =>
    submit({
      operation,
      qualityTier: tier,
      durationSeconds: duration,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      referenceAssetIds: uploads.map((asset) => asset.id),
      extra: { sound },
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
    });

  const cover = source?.work.current_version?.cover_url ?? source?.work.cover_url;
  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  // One element rendered in two slots: the wide layout's aside and the narrow
  // layout's sheet. Only one of them is ever visible, so the controls stay
  // bound to a single piece of state either way.
  const paramsPanel = (
    <>
      <div>
        <TextArea
          label={t('promptLabel')}
          placeholder={t('promptPlaceholder')}
          value={prompt}
          maxLength={PROMPT_MAX_LENGTH}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <p className="tabular mt-1 text-right text-[11px] text-muted">
          {prompt.length}/{PROMPT_MAX_LENGTH}
        </p>
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
              {estimate}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">{t('estimateHint')}</p>
          </div>
          <p className="tabular shrink-0 text-sm font-semibold text-amber">{price}</p>
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
    </>
  );

  return (
    <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[184px_minmax(0,1fr)_340px]">
      <div className="order-2 min-w-0 lg:order-none">
        <SourceMaterialRail
          source={source}
          reference={reference}
          uploads={uploads}
          onUploaded={(asset) => setUploads((current) => [...current, asset])}
          onRemove={(id) => setUploads((current) => current.filter((asset) => asset.id !== id))}
        />
      </div>

      <div className="order-1 flex min-w-0 flex-col gap-4 lg:order-none">
        {aspect === PORTRAIT_ASPECT ? (
          // A vertical framing is the one the author cannot judge from a
          // 16:9 box, so that is where the phone frame earns its place.
          <DevicePreview
            poster={cover}
            title={source?.work.title ?? t('promptLabel')}
            defaultDeviceId={DEFAULT_DEVICE_ID}
            maxHeight={480}
          />
        ) : (
          <Poster
            src={cover}
            alt={source?.work.title ?? t('promptLabel')}
            aspect="video"
            className="border border-border"
          />
        )}

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

      <aside className="order-3 hidden flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4 lg:flex">
        <h2 className="text-sm font-semibold">{t('howToGenerate')}</h2>
        {paramsPanel}
        <Button
          size="lg"
          onClick={runSubmit}
          disabled={!canSubmit}
          loading={submitting}
          icon={<IconSparkle className="size-5" />}
        >
          {submitting ? t('submitting') : t('submit')}
        </Button>
      </aside>

      {/* Keeps the end of the page clear of the fixed bar below. */}
      <div aria-hidden="true" className="safe-mb order-4 h-24 lg:hidden" />

      <div className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface lg:hidden">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-3">
          {error && !paramsOpen ? (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex items-center justify-between gap-3 text-xs">
            <p className="tabular font-semibold text-amber">{price}</p>
            <p className="tabular flex items-center gap-1.5 text-muted">
              <IconClock className="size-3.5" />
              {estimate}
            </p>
          </div>
          {/* The submit button takes the rest of the row rather than sizing to
              its label: it is the only control here that spends credits, and
              the label is the longest string in three languages. */}
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => setParamsRequested(true)}
              icon={<IconGear className="size-4" />}
              className="shrink-0"
            >
              {t('adjustParams')}
            </Button>
            <Button
              onClick={runSubmit}
              disabled={!canSubmit}
              loading={submitting}
              icon={<IconSparkle className="size-4" />}
              className="min-w-0 flex-1"
            >
              {submitting ? t('submitting') : t('submit')}
            </Button>
          </div>
        </div>
      </div>

      <Sheet
        open={paramsOpen}
        onClose={() => setParamsRequested(false)}
        title={t('howToGenerate')}
        description={t('adjustParamsHint')}
        footer={
          <Button variant="secondary" fullWidth onClick={() => setParamsRequested(false)}>
            {t('paramsDone')}
          </Button>
        }
      >
        {paramsPanel}
      </Sheet>
    </div>
  );
}
