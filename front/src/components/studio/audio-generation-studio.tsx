'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useRef, useState } from 'react';

import { OptionGroup } from '@/components/studio/option-group';
import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { PromptComposer } from '@/components/studio/prompt-composer';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import {
  KNOWN_PRESET_KEYS,
  useStyleAndSkillPicker,
} from '@/components/studio/style-and-skill-picker';
import { IconButton } from '@/components/ui/button';
import { Select, TextInput } from '@/components/ui/field';
import { IconClose, IconMic, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import type { QualityTier, WorkDetail } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import { FALLBACK_VOICES, unionVoices, useGenerationModels } from '@/lib/use-generation-models';
import { type Asset, declareConsent, uploadFile } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';

// The shared submit schema always wants a valid `aspect_ratio` (backend
// pattern `^\d{1,2}:\d{1,2}$`); audio has no aspect control of its own, so
// this rides along as the same default the field would otherwise show.
const AUDIO_ASPECT_RATIO = '16:9';
// `AUDIO_CLONE_MAX_REFERENCES` in `app/api/schemas/jobs.py` — a clone call
// takes exactly one reference voice.
const CLONE_ACCEPT = 'audio/mpeg,audio/wav';
// `SUBJECT_MAX_LENGTH` in `app/domain/consent/service.py`.
const CONSENT_SUBJECT_MAX_LENGTH = 255;

type AudioMode = 'voice' | 'clone';

/** `/create/new`'s `audio_generation` mode. The remaining studio that still
 * shows the creation-skill Select on `useStyleAndSkillPicker` (image and
 * video apply template skills from the prompt `@` menu). Unlike
 * `VideoGenerationStudio`, there is no `?styleId=` deep link into this shell
 * — the style gallery's inspiration surfaces only ever link into video mode
 * — so it has no `initialStyleParams`/`initialStyleGalleryId` props; the
 * style/skill picker is still reachable from its own button in the panel.
 *
 * Voice selection is now two modes rather than one fixed six-item `Select`
 * (see `.cursor/plans/音频创作闭环与供应商适配...plan.md` phase 4): "预设音色"
 * picks a model's own preset roster (`GenerationModelOption.voices`, sourced
 * live from `app.providers.model_catalog.voices_for_model`), "克隆音色"
 * uploads a short reference sample instead (`voice_sample` purpose,
 * `reference_asset_ids`) — the two are mutually exclusive per
 * `AUDIO_CLONE_MAX_REFERENCES=1` on the backend.
 *
 * Cloning needs the voice owner's own consent (深度合成管理规定 §14): the
 * backend refuses a clone submit with `ASSET_RIGHTS_REQUIRED` until a voice
 * consent exists for the sample, so the clone tab collects who the voice
 * belongs to plus an explicit confirmation, and records the consent
 * (`declareConsent`) right before submitting. */
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
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});

  // -- model / voice picking -------------------------------------------
  const modelOptions = useGenerationModels('audio_generation');
  const [forcedModel, setForcedModel] = useState('');
  const selectedModelOption = modelOptions.find((option) => option.model === forcedModel);

  // No model picked ("自动选择"): show the union of every known model's own
  // roster rather than nothing, so the picker still offers real voice ids
  // instead of forcing a model pick just to see one.
  const modelUnionVoices = useMemo(() => unionVoices(modelOptions), [modelOptions]);

  const availableVoices = forcedModel
    ? (selectedModelOption?.voices ?? [])
    : modelUnionVoices.length > 0
      ? modelUnionVoices
      : [...FALLBACK_VOICES];

  const [mode, setMode] = useState<AudioMode>('voice');
  const [pickedVoice, setPickedVoice] = useState<string>(FALLBACK_VOICES[0]);

  // Keeps the voice `Select` valid as the roster changes under it (model
  // switched, or the live catalogue finished loading) instead of silently
  // submitting a voice id the newly-picked model does not recognize.
  const voice = availableVoices.includes(pickedVoice)
    ? pickedVoice
    : (availableVoices[0] ?? pickedVoice);

  const pickModel = (model: string) => {
    setForcedModel(model);
    // A model with no known preset roster (fal's single-call clone models,
    // e.g. `minimax/voice-clone`) has nothing for the "预设音色" tab to show —
    // switch to the clone tab for the user rather than leaving them on an
    // empty `Select`. Only on an explicit model pick, never on "自动选择"
    // (where some other candidate model may well have a real roster).
    const option = modelOptions.find((candidate) => candidate.model === model);
    if (model && option && !option.voices?.length) setMode('clone');
  };

  // -- clone reference upload + the voice owner's consent ---------------
  const [cloneAsset, setCloneAsset] = useState<Asset | null>(null);
  const [cloneUploading, setCloneUploading] = useState(false);
  const cloneInputRef = useRef<HTMLInputElement>(null);
  const [consentSubject, setConsentSubject] = useState('');
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  // The sample a consent has already been recorded for — a new sample needs
  // its own declaration.
  const [consentAssetId, setConsentAssetId] = useState<string | null>(null);

  const pickClone = async (file: File | undefined) => {
    if (!file) return;
    setCloneUploading(true);
    try {
      setCloneAsset(await uploadFile(file, 'voice_sample'));
      setConsentConfirmed(false);
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setCloneUploading(false);
      if (cloneInputRef.current) cloneInputRef.current.value = '';
    }
  };

  const removeClone = () => {
    setCloneAsset(null);
    setConsentConfirmed(false);
  };

  const consentRecorded = cloneAsset !== null && consentAssetId === cloneAsset.id;
  const cloneReady =
    cloneAsset !== null &&
    (consentRecorded || (consentSubject.trim().length > 0 && consentConfirmed));

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
    prompt.trim().length > 0 &&
    rightsConfirmed &&
    !submitting &&
    (quote?.sufficient ?? true) &&
    (mode === 'voice' || cloneReady);

  const runSubmit = async () => {
    if (mode === 'clone' && cloneAsset && !consentRecorded) {
      try {
        await declareConsent(cloneAsset.id, { type: 'voice', subject: consentSubject.trim() });
        setConsentAssetId(cloneAsset.id);
      } catch {
        notify(t('consentFailed'), 'error');
        return;
      }
    }
    submit({
      operation: 'audio_generation',
      qualityTier: tier,
      durationSeconds: 0,
      prompt: prompt.trim(),
      aspectRatio: AUDIO_ASPECT_RATIO,
      referenceAssetIds: mode === 'clone' && cloneAsset ? [cloneAsset.id] : [],
      extra: mode === 'clone' ? { ...presetExtra } : { voice, ...presetExtra },
      forcedModel: forcedModel || undefined,
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
    });
  };

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const paramsPanel = (
    <>
      {styleAndSkillPicker}

      <Select
        label={t('modelSelectLabel')}
        hint={t('modelSelectHint')}
        value={forcedModel}
        onChange={(event) => pickModel(event.target.value)}
        options={[
          { value: '', label: t('modelAuto') },
          ...modelOptions.map((option) => ({ value: option.model, label: option.label })),
        ]}
      />

      <OptionGroup
        label={t('audioModeLabel')}
        value={mode}
        onChange={setMode}
        columns={2}
        options={[
          { value: 'voice', label: t('audioModeVoice'), hint: t('audioModeVoiceHint') },
          { value: 'clone', label: t('audioModeClone'), hint: t('audioModeCloneHint') },
        ]}
      />

      {mode === 'voice' ? (
        <Select
          label={t('voice')}
          hint={t('voiceHint')}
          value={voice}
          onChange={(event) => setPickedVoice(event.target.value)}
          options={availableVoices.map((value) => ({
            value,
            label: value,
          }))}
        />
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted">{t('cloneUploadHint')}</p>
          {cloneAsset ? (
            <div className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-2.5">
              <IconMic className="size-4 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{t('cloneUploaded')}</p>
                {cloneAsset.url ? (
                  <audio controls src={cloneAsset.url} className="mt-1 h-8 w-full" />
                ) : null}
              </div>
              <IconButton
                label={t('cloneRemove')}
                size="sm"
                variant="secondary"
                onClick={removeClone}
              >
                <IconClose className="size-3.5" />
              </IconButton>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => cloneInputRef.current?.click()}
              disabled={cloneUploading}
              className="flex items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-dashed border-border px-3 py-3 text-xs text-muted hover:border-border-strong hover:text-text disabled:opacity-60"
            >
              {cloneUploading ? <Spinner className="size-4" /> : <IconUpload className="size-4" />}
              {t('cloneUploadButton')}
            </button>
          )}
          <input
            ref={cloneInputRef}
            type="file"
            accept={CLONE_ACCEPT}
            aria-label={t('cloneUploadButton')}
            className="sr-only"
            onChange={(event) => void pickClone(event.target.files?.[0])}
          />
          {cloneAsset ? (
            consentRecorded ? (
              <p className="text-xs text-muted">{t('consentDeclared')}</p>
            ) : (
              <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border p-2.5">
                <TextInput
                  label={t('consentSubjectLabel')}
                  hint={t('consentSubjectHint')}
                  value={consentSubject}
                  maxLength={CONSENT_SUBJECT_MAX_LENGTH}
                  required
                  onChange={(event) => setConsentSubject(event.target.value)}
                />
                <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
                  <input
                    type="checkbox"
                    checked={consentConfirmed}
                    onChange={(event) => setConsentConfirmed(event.target.checked)}
                    className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
                  />
                  {t('consentConfirmVoice')}
                </label>
              </div>
            )
          ) : null}
        </div>
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

  // Same `promptSlot` placement as image/video — the field stays next to
  // the preview on every breakpoint. No polish / `@` mention: audio still
  // applies skills from the params-panel Select. `tip` folds the shell's
  // former standalone `directHint` box into this card (video's pattern).
  const promptComposer = (
    <PromptComposer
      prompt={prompt}
      onChange={setPrompt}
      tip={{ title: t('directHint'), body: t('directHintBody') }}
    />
  );

  return (
    <GenerationStudioShell
      source={source}
      reference={reference}
      uploads={[]}
      onUploaded={() => {}}
      onRemove={() => {}}
      isAudio
      promptSlot={promptComposer}
      canSubmit={canSubmit}
      submitting={submitting}
      onSubmit={() => void runSubmit()}
      price={price}
      estimate={estimate}
      error={error}
    >
      {paramsPanel}
    </GenerationStudioShell>
  );
}
