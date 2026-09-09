'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { GenerationStudioShell } from '@/components/studio/generation-studio-shell';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptComposer } from '@/components/studio/prompt-composer';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { Switch, TextArea, TextInput } from '@/components/ui/field';
import type { Locale } from '@/i18n/routing';
import type { QualityTier } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import { useGenerationSubmit } from '@/lib/use-generation-submit';

// `MUSIC_SFX_MIN/MAX_DURATION_SECONDS` in `app/api/schemas/jobs.py` — only
// enforced for `audio_style="sfx"`, and only when the caller actually sets
// a duration; leaving it at 0 lets the model pick its own length.
const SFX_MIN_DURATION_SECONDS = 1;
const SFX_MAX_DURATION_SECONDS = 22;
// Same "no aspect control of its own" rider `AudioGenerationStudio` carries.
const MUSIC_ASPECT_RATIO = '16:9';

type AudioStyle = 'music' | 'sfx';

/** `/create/new`'s `music_generation` mode (`Operation.MUSIC_GENERATION`,
 * see the module docstring on the backend enum) — BGM or a one-shot sound
 * effect for the editor's audio track, never the discrete-voice `Select`
 * `AudioGenerationStudio` shows: there is no voice here, only a text
 * `prompt` (+ optional lyrics for a sung BGM).
 *
 * A standalone shell rather than a third mode bolted onto
 * `AudioGenerationStudio`: the two operations bill differently (`Audio
 * Pricing.per_10k_characters` vs. `MusicPricing.per_request`) and take a
 * different input shape entirely (`audio_style`/`lyrics`/`is_instrumental`
 * vs. `voice`/a clone reference) — see the plan's own "不复用 AUDIO_
 * GENERATION" rationale. */
export function MusicGenerationStudio({ initialPrompt }: { initialPrompt?: string }) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;

  const [prompt, setPrompt] = useState(initialPrompt ?? '');
  const [audioStyle, setAudioStyle] = useState<AudioStyle>('music');
  const [lyrics, setLyrics] = useState('');
  const [isInstrumental, setIsInstrumental] = useState(true);
  const [sfxDuration, setSfxDuration] = useState('');
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);

  const parsedSfxDuration = Number.parseInt(sfxDuration, 10);
  const sfxDurationSeconds =
    audioStyle === 'sfx' && Number.isFinite(parsedSfxDuration) && parsedSfxDuration > 0
      ? parsedSfxDuration
      : 0;
  const sfxDurationInvalid =
    audioStyle === 'sfx' &&
    sfxDuration.trim() !== '' &&
    (!Number.isFinite(parsedSfxDuration) ||
      parsedSfxDuration < SFX_MIN_DURATION_SECONDS ||
      parsedSfxDuration > SFX_MAX_DURATION_SECONDS);

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation: 'music_generation', qualityTier: tier, durationSeconds: 0 },
    { label: t('submit') },
  );

  const canSubmit =
    prompt.trim().length > 0 &&
    rightsConfirmed &&
    !submitting &&
    !sfxDurationInvalid &&
    (quote?.sufficient ?? true);

  const runSubmit = () =>
    submit({
      operation: 'music_generation',
      qualityTier: tier,
      durationSeconds: sfxDurationSeconds,
      prompt: prompt.trim(),
      aspectRatio: MUSIC_ASPECT_RATIO,
      referenceAssetIds: [],
      extra: {
        audio_style: audioStyle,
        is_instrumental: audioStyle === 'music' ? isInstrumental : undefined,
        lyrics:
          audioStyle === 'music' && !isInstrumental && lyrics.trim() ? lyrics.trim() : undefined,
      },
      maxCredits: quote?.credits,
    });

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const paramsPanel = (
    <>
      <OptionGroup
        label={t('musicAudioStyleLabel')}
        value={audioStyle}
        onChange={setAudioStyle}
        columns={2}
        options={[
          { value: 'music', label: t('musicStyleMusic') },
          { value: 'sfx', label: t('musicStyleSfx') },
        ]}
      />

      {audioStyle === 'music' ? (
        <>
          <Switch
            checked={isInstrumental}
            onChange={setIsInstrumental}
            label={t('musicInstrumentalLabel')}
            description={t('musicInstrumentalHint')}
          />
          {!isInstrumental ? (
            <TextArea
              label={t('musicLyricsLabel')}
              hint={t('musicLyricsHint')}
              value={lyrics}
              onChange={(event) => setLyrics(event.target.value)}
              placeholder={t('musicLyricsPlaceholder')}
              rows={5}
            />
          ) : null}
        </>
      ) : (
        <TextInput
          label={t('musicDurationLabel')}
          hint={t('musicDurationHint')}
          type="number"
          min={SFX_MIN_DURATION_SECONDS}
          max={SFX_MAX_DURATION_SECONDS}
          value={sfxDuration}
          onChange={(event) => setSfxDuration(event.target.value)}
          error={sfxDurationInvalid ? t('musicDurationInvalid') : undefined}
        />
      )}

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

  const promptComposer = (
    <PromptComposer
      prompt={prompt}
      onChange={setPrompt}
      tip={{
        title: t('musicDirectHint'),
        body: audioStyle === 'music' ? t('musicDirectHintBodyMusic') : t('musicDirectHintBodySfx'),
      }}
    />
  );

  return (
    <GenerationStudioShell
      uploads={[]}
      onUploaded={() => {}}
      onRemove={() => {}}
      isAudio
      promptSlot={promptComposer}
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
