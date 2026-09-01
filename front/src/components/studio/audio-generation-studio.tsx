'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { PromptField } from '@/components/studio/prompt-field';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { KNOWN_PRESET_KEYS, useStyleAndSkillPicker } from '@/components/studio/style-and-skill-picker';
import { Select } from '@/components/ui/field';
import type { Locale } from '@/i18n/routing';
import type { QualityTier, WorkDetail } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';

// Fixed roster, mirrored by `AUDIO_VOICES` in `app/api/schemas/jobs.py` — these
// are the provider's own voice ids, so they travel through untranslated.
const AUDIO_VOICES = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'] as const;
// The shared submit schema always wants a valid `aspect_ratio` (backend
// pattern `^\d{1,2}:\d{1,2}$`); audio has no aspect control of its own, so
// this rides along as the same default the field would otherwise show.
const AUDIO_ASPECT_RATIO = '16:9';

/** `/create/new`'s `audio_generation` mode. The remaining studio that still
 * shows the creation-skill Select on `useStyleAndSkillPicker` (image and
 * video apply template skills from the prompt `@` menu). Unlike
 * `VideoGenerationStudio`, there is no `?styleId=` deep link into this shell
 * — the style gallery's inspiration surfaces only ever link into video mode
 * — so it has no `initialStyleParams`/`initialStyleGalleryId` props; the
 * style/skill picker is still reachable from its own button in the panel. */
export function AudioGenerationStudio({
  source,
  reference,
  initialPrompt,
}: {
  source?: StudioSource;
  reference?: WorkDetail;
  initialPrompt?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [voice, setVoice] = useState<string>(AUDIO_VOICES[0]);
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});

  /** Shared by presets, skills and the style gallery: all three apply the same `prompt`/extras shape (no `aspect_ratio` here — audio has no aspect control). */
  const applyParams = (params: Record<string, unknown>) => {
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

  const {
    node: styleAndSkillPicker,
    appliedSkillIds,
    appliedStyleGalleryId,
  } = useStyleAndSkillPicker({
    operation: 'audio_generation',
    onApplyParams: applyParams,
  });

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation: 'audio_generation', qualityTier: tier, durationSeconds: 0 },
    { label: t('submit') },
  );

  const canSubmit =
    prompt.trim().length > 0 && rightsConfirmed && !submitting && (quote?.sufficient ?? true);

  const removeUpload = (assetId: string) => {
    setUploads((current) => current.filter((asset) => asset.id !== assetId));
  };

  const runSubmit = () =>
    submit({
      operation: 'audio_generation',
      qualityTier: tier,
      durationSeconds: 0,
      prompt: prompt.trim(),
      aspectRatio: AUDIO_ASPECT_RATIO,
      referenceAssetIds: uploads.map((asset) => asset.id),
      extra: { voice, ...presetExtra },
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

      <PromptField prompt={prompt} onChange={setPrompt} />

      <Select
        label={t('voice')}
        hint={t('voiceHint')}
        value={voice}
        onChange={(event) => setVoice(event.target.value)}
        options={AUDIO_VOICES.map((value) => ({
          value,
          label: value.charAt(0).toUpperCase() + value.slice(1),
        }))}
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
      isAudio
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
