'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptField } from '@/components/studio/prompt-field';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import {
  KNOWN_PRESET_KEYS,
  useStyleAndSkillPicker,
} from '@/components/studio/style-and-skill-picker';
import { Select, TextInput } from '@/components/ui/field';
import {
  IconChevronDown,
  IconGear,
  IconLandscape,
  IconPortrait,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { QualityTier, WorkDetail } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';

type Operation = 'text_to_video' | 'image_to_video' | 'video_to_video';
type ReferenceMode = 'input_references' | 'frame_images';
type Orientation = 'landscape' | 'portrait';

// No `1:1`: every framing the studio offers is either wider or taller than
// square, so orientation is always a meaningful first choice.
const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9'] as const;
const PORTRAIT_ASPECTS = ['9:16', '3:4'] as const;
const ASPECTS = [...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS] as const;
const PORTRAIT_ASPECT = '9:16';
const DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);

/**
 * `/create/new` (`text_to_video` / `image_to_video` modes) and
 * `/remix/[workId]` (always `image_to_video` — remix has no image/audio path
 * yet, see that page). Keeps the style preset / creation skill / system style
 * picker exactly as it was before the split (`ImageGenerationStudio` is the
 * one shell that dropped it).
 */
export function VideoGenerationStudio({
  operation: initialOperation,
  source,
  reference,
  initialPrompt,
  initialStyleParams,
  initialStyleGalleryId,
}: {
  operation: 'text_to_video' | 'image_to_video';
  /** A licensed remix source. Submitted as `source_work_id`. */
  source?: StudioSource;
  /** A work the idea came from, carried over from the discover feed. */
  reference?: WorkDetail;
  initialPrompt?: string;
  /** A style gallery entry's `params`, applied once on mount (from `?styleId=`). */
  initialStyleParams?: Record<string, unknown>;
  /** The catalogue id behind `initialStyleParams`; submitted as `style_gallery_id`. */
  initialStyleGalleryId?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [aspect, setAspect] = useState<string>('16:9');
  const [duration, setDuration] = useState(8);
  const [seed, setSeed] = useState('');
  const [referenceMode, setReferenceMode] = useState<ReferenceMode>('input_references');
  const [firstFrameAssetId, setFirstFrameAssetId] = useState('');
  const [lastFrameAssetId, setLastFrameAssetId] = useState('');
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});
  const [moreSettingsOpen, setMoreSettingsOpen] = useState(false);

  /** Shared by presets, skills and the style gallery: all three apply the same `prompt`/`aspect_ratio`/extras shape. */
  const applyParams = (params: Record<string, unknown>) => {
    const aspectRatio = params.aspect_ratio;
    if (typeof aspectRatio === 'string' && (ASPECTS as readonly string[]).includes(aspectRatio)) {
      setAspect(aspectRatio);
    }
    const promptSuffix = params.prompt_suffix;
    if (typeof params.prompt === 'string' && params.prompt.trim()) {
      setPrompt(params.prompt);
    } else if (typeof promptSuffix === 'string' && promptSuffix.trim()) {
      setPrompt((current) => (current.trim() ? `${current}, ${promptSuffix}` : promptSuffix));
    }
    const extra = Object.fromEntries(
      Object.entries(params).filter(([key]) => !KNOWN_PRESET_KEYS.has(key)),
    );
    if (Object.keys(extra).length > 0) setPresetExtra((current) => ({ ...current, ...extra }));
  };

  const hasVideoReference = uploads.some((asset) => asset.media_type === 'video');
  const hasImageReference = uploads.some((asset) => asset.media_type === 'image');
  let operation: Operation = initialOperation;
  if (initialOperation === 'text_to_video') {
    if (referenceMode === 'frame_images' && firstFrameAssetId) operation = 'image_to_video';
    else if (hasVideoReference) operation = 'video_to_video';
    else if (source || hasImageReference) operation = 'image_to_video';
  }

  const {
    node: styleAndSkillPicker,
    appliedSkillIds,
    appliedStyleGalleryId,
    styleHint,
  } = useStyleAndSkillPicker({
    operation,
    initialStyleParams,
    initialStyleGalleryId,
    onApplyParams: applyParams,
  });

  // Derived, not its own state: an independent `orientation` could disagree
  // with `aspect` the moment a preset/skill/style applies one directly, and
  // then the "adjust while rendering" fix for that disagreement would have to
  // run every render. Deriving it removes the disagreement instead.
  const orientation: Orientation = (LANDSCAPE_ASPECTS as readonly string[]).includes(aspect)
    ? 'landscape'
    : 'portrait';
  const aspectOptions = orientation === 'landscape' ? LANDSCAPE_ASPECTS : PORTRAIT_ASPECTS;
  const imageUploads = uploads.filter((asset) => asset.media_type === 'image');
  const parsedSeed = seed.trim() ? Number(seed) : undefined;
  const seedValid =
    parsedSeed === undefined ||
    (Number.isInteger(parsedSeed) && parsedSeed >= 0 && parsedSeed <= 2 ** 31 - 1);

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation, qualityTier: tier, durationSeconds: duration },
    { label: t('submit') },
  );

  const frameSelectionValid = referenceMode !== 'frame_images' || Boolean(firstFrameAssetId);
  const canSubmit =
    prompt.trim().length > 0 &&
    rightsConfirmed &&
    frameSelectionValid &&
    seedValid &&
    !submitting &&
    (quote?.sufficient ?? true);

  const removeUpload = (assetId: string) => {
    setUploads((current) => current.filter((asset) => asset.id !== assetId));
    if (firstFrameAssetId === assetId) setFirstFrameAssetId('');
    if (lastFrameAssetId === assetId) setLastFrameAssetId('');
  };

  const runSubmit = () =>
    submit({
      operation,
      qualityTier: tier,
      durationSeconds: duration,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      seed: parsedSeed,
      referenceAssetIds: referenceMode === 'frame_images' ? [] : uploads.map((asset) => asset.id),
      videoOptions: {
        resolution: '2K',
        reference_mode: referenceMode,
        first_frame_asset_id: referenceMode === 'frame_images' ? firstFrameAssetId || null : null,
        last_frame_asset_id: referenceMode === 'frame_images' ? lastFrameAssetId || null : null,
      },
      extra: { sound, ...presetExtra },
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
    });

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const paramsPanel = (
    <>
      {styleAndSkillPicker}

      <PromptField
        prompt={prompt}
        onChange={setPrompt}
        polishContext={{
          operation,
          aspectRatio: aspect,
          durationSeconds: duration,
          qualityTier: tier,
          styleHint,
          hasReference: uploads.length > 0 || Boolean(source),
        }}
        onPolishAccept={setPrompt}
      />

      <OptionGroup
        label={t('orientation')}
        value={orientation}
        onChange={(value) =>
          setAspect(value === 'landscape' ? LANDSCAPE_ASPECTS[0] : PORTRAIT_ASPECTS[0])
        }
        columns={2}
        options={[
          {
            value: 'landscape' as const,
            label: t('orientationLandscape'),
            icon: <IconLandscape className="size-4" />,
          },
          {
            value: 'portrait' as const,
            label: t('orientationPortrait'),
            icon: <IconPortrait className="size-4" />,
          },
        ]}
      />
      <OptionGroup
        label={t('aspect')}
        value={aspect}
        onChange={setAspect}
        options={aspectOptions.map((value) => ({ value, label: value }))}
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

      <div className="rounded-[var(--radius-sm)] border border-border">
        <button
          type="button"
          onClick={() => setMoreSettingsOpen((current) => !current)}
          aria-expanded={moreSettingsOpen}
          className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-sm font-medium"
        >
          <span className="flex items-center gap-2">
            <IconGear className="size-4 text-muted" />
            {t('moreSettings')}
          </span>
          <IconChevronDown
            className={cn(
              'size-4 text-muted transition-transform',
              moreSettingsOpen && 'rotate-180',
            )}
          />
        </button>
        {moreSettingsOpen ? (
          <div className="flex flex-col gap-4 border-t border-border p-3">
            <Select
              label={t('resolution')}
              hint={t('resolutionHint')}
              value="2K"
              disabled
              options={[{ value: '2K', label: '2K' }]}
            />
            <TextInput
              label={t('seed')}
              hint={t('seedHint')}
              error={seedValid ? undefined : t('seedInvalid')}
              type="number"
              min="0"
              max={String(2 ** 31 - 1)}
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
            />
          </div>
        ) : null}
      </div>
      <OptionGroup
        label={t('referenceMode')}
        value={referenceMode}
        onChange={setReferenceMode}
        columns={2}
        options={[
          { value: 'input_references', label: t('referenceModeInputs') },
          { value: 'frame_images', label: t('referenceModeFrames') },
        ]}
      />
      {referenceMode === 'frame_images' ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label={t('firstFrameSelect')}
            hint={t('firstFrameRequired')}
            value={firstFrameAssetId}
            onChange={(event) => setFirstFrameAssetId(event.target.value)}
            options={[
              { value: '', label: t('selectUploadedImage') },
              ...imageUploads.map((asset, index) => ({
                value: asset.id,
                label: t('uploadedImage', { index: index + 1 }),
              })),
            ]}
          />
          <Select
            label={t('lastFrameSelect')}
            value={lastFrameAssetId}
            onChange={(event) => setLastFrameAssetId(event.target.value)}
            options={[
              { value: '', label: t('lastFrameNone') },
              ...imageUploads.map((asset, index) => ({
                value: asset.id,
                label: t('uploadedImage', { index: index + 1 }),
              })),
            ]}
          />
        </div>
      ) : (
        <p className="text-xs text-muted">{t('inputReferencesHint')}</p>
      )}

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

      <QualityTierField tier={tier} onChange={setTier} quote={quote} />

      <RightsAndEstimate
        rightsConfirmed={rightsConfirmed}
        onRightsChange={setRightsConfirmed}
        quote={quote}
        quoteFailed={quoteFailed}
        estimate={estimate}
        price={price}
        error={error}
      />
    </>
  );

  return (
    <GenerationStudioShell
      source={source}
      reference={reference}
      uploads={uploads}
      onUploaded={(asset) => setUploads((current) => [...current, asset])}
      onRemove={removeUpload}
      isPortraitPreview={aspect === PORTRAIT_ASPECT}
      canSubmit={canSubmit}
      submitting={submitting}
      onSubmit={runSubmit}
      price={price}
      estimate={estimate}
      error={error}
    >
      {paramsPanel}
    </GenerationStudioShell>
  );
}
