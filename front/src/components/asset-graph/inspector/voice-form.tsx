'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  CustomAttributesEditor,
  customIncomplete,
  type CustomRow,
} from '@/components/library/variant-attributes-form';
import { Button } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { AGE_STAGES, keysOf } from '@/features/image-assets/vocabulary';
import { ApiError } from '@/lib/api/errors';
import type { CharacterVoice, GenerationModelOption } from '@/lib/api/types';
import { declareConsent, uploadFile } from '@/lib/upload';

import { VoicePlayButton } from '../voice-play-button';

/** `characters.voices` limits. */
export const MAX_VOICE_NAME_LENGTH = 40;
export const MAX_PREVIEW_TEXT_LENGTH = 200;
export const VOICE_USES = ['dialogue', 'inner_monologue', 'narration'] as const;
const SPEED_MIN = 0.25;
const SPEED_MAX = 4;

export interface VoiceDraft {
  name: string;
  description: string;
  source: 'preset' | 'clone';
  model: string;
  voice: string;
  speed: number | null;
  emotion: string;
  ageStage: string;
  attributeEmotion: string;
  use: string;
  custom: CustomRow[];
  previewText: string;
  sampleAssetId: string | null;
  sampleUrl: string | null;
}

export function voiceDraft(voice?: Partial<CharacterVoice> | null, name = ''): VoiceDraft {
  return {
    name: voice?.name ?? name,
    description: voice?.description ?? '',
    source: voice?.source ?? 'preset',
    model: voice?.model ?? '',
    voice: voice?.voice ?? '',
    speed: voice?.params?.speed ?? null,
    emotion: voice?.params?.emotion ?? '',
    ageStage: voice?.attributes?.age_stage ?? '',
    attributeEmotion: voice?.attributes?.emotion ?? '',
    use: voice?.attributes?.use ?? '',
    custom: (voice?.attributes?.custom ?? []).map((item) => ({ ...item })),
    previewText: voice?.preview_text ?? '',
    sampleAssetId: voice?.sample?.asset_id ?? null,
    sampleUrl: voice?.sample?.url ?? null,
  };
}

/** The request body for a voice create / update / derive. */
export function voiceBody(
  draft: VoiceDraft,
  model?: GenerationModelOption,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (draft.speed != null && model?.voice_params?.includes('speed')) params.speed = draft.speed;
  if (draft.emotion && model?.voice_params?.includes('emotion')) params.emotion = draft.emotion;
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    source: draft.source,
    model: draft.source === 'preset' ? draft.model : draft.model || null,
    voice: draft.source === 'preset' ? draft.voice : null,
    params,
    attributes: {
      age_stage: draft.ageStage || null,
      emotion: draft.attributeEmotion.trim() || null,
      use: draft.use || null,
      custom: draft.custom
        .map((row) => ({ key: row.key.trim(), value: row.value.trim() }))
        .filter((row) => row.key && row.value),
    },
    sample_asset_id: draft.source === 'clone' ? draft.sampleAssetId : null,
    preview_text: draft.previewText.trim() || null,
  };
}

/**
 * A voice's fields: a preset (model → its roster's voice → only the knobs
 * that model takes) or a clone (upload a sample and declare the speaker's
 * consent first), then its attributes and preview text. Used to create,
 * edit and derive voices; mounted per voice, so state starts from it.
 */
export function VoiceForm({
  initial,
  models,
  submitLabel,
  busy,
  onSubmit,
}: {
  initial: VoiceDraft;
  models: GenerationModelOption[];
  submitLabel: string;
  busy?: boolean;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const t = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  const [draft, setDraft] = useState<VoiceDraft>(initial);
  const [uploading, setUploading] = useState(false);
  const [subject, setSubject] = useState('');
  const [consented, setConsented] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const presetModels = models.filter((option) => option.voices?.length);
  const model = models.find((option) => option.model === draft.model);
  const roster = model?.voices ?? [];
  const set = (patch: Partial<VoiceDraft>) => setDraft((current) => ({ ...current, ...patch }));

  const uploadSample = async (file: File) => {
    if (!subject.trim() || !consented) {
      setError(t('cloneConsentFirst'));
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const asset = await uploadFile(file, 'voice_sample');
      await declareConsent(asset.id, { type: 'voice', subject: subject.trim() });
      set({ sampleAssetId: asset.id, sampleUrl: asset.url ?? null });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('genericError'));
    } finally {
      setUploading(false);
    }
  };

  const ready =
    draft.name.trim().length > 0 &&
    !customIncomplete(draft.custom) &&
    (draft.source === 'preset'
      ? Boolean(draft.model && draft.voice)
      : Boolean(draft.sampleAssetId));

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onSubmit(voiceBody(draft, model));
      }}
    >
      <TextInput
        label={t('voiceName')}
        value={draft.name}
        maxLength={MAX_VOICE_NAME_LENGTH}
        placeholder={t('voiceNamePlaceholder')}
        onChange={(event) => set({ name: event.target.value })}
      />
      <div role="radiogroup" aria-label={t('voiceSource')} className="flex gap-4 text-sm">
        {(['preset', 'clone'] as const).map((value) => (
          <label key={value} className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              checked={draft.source === value}
              onChange={() => set({ source: value })}
              className="accent-[var(--primary)]"
            />
            {value === 'preset' ? t('voicePreset') : t('voiceClone')}
          </label>
        ))}
      </div>

      {draft.source === 'preset' ? (
        <>
          <Select
            label={t('voiceModel')}
            value={draft.model}
            onChange={(event) =>
              set({ model: event.target.value, voice: '', speed: null, emotion: '' })
            }
            options={[
              { value: '', label: t('pickModel') },
              ...presetModels.map((option) => ({ value: option.model, label: option.label })),
              // Keep a stored model selectable even if it is not enabled now.
              ...(draft.model && !presetModels.some((o) => o.model === draft.model)
                ? [{ value: draft.model, label: draft.model }]
                : []),
            ]}
          />
          <Select
            label={t('voicePick')}
            value={draft.voice}
            disabled={!draft.model}
            onChange={(event) => set({ voice: event.target.value })}
            options={[
              { value: '', label: t('pickVoice') },
              ...roster.map((voice) => ({ value: voice, label: voice })),
              ...(draft.voice && !roster.includes(draft.voice)
                ? [{ value: draft.voice, label: draft.voice }]
                : []),
            ]}
          />
          {model?.voice_params?.includes('speed') ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="flex justify-between text-xs text-muted">
                {t('voiceSpeed')}
                <span>×{(draft.speed ?? 1).toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={SPEED_MIN}
                max={SPEED_MAX}
                step={0.05}
                value={draft.speed ?? 1}
                onChange={(event) => set({ speed: Number(event.target.value) })}
                className="accent-[var(--primary)]"
              />
            </label>
          ) : null}
          {model?.voice_params?.includes('emotion') ? (
            <Select
              label={t('voiceEmotionParam')}
              value={draft.emotion}
              onChange={(event) => set({ emotion: event.target.value })}
              options={[
                { value: '', label: t('emotionNone') },
                ...(model.voice_emotions ?? []).map((value) => ({
                  value,
                  label: t(`emotion.${value}`),
                })),
              ]}
            />
          ) : null}
        </>
      ) : (
        <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
          {draft.sampleUrl ? (
            <div className="flex items-center gap-2 text-xs text-muted">
              {t('sampleReady')}
              <VoicePlayButton url={draft.sampleUrl} label={t('playSample')} />
            </div>
          ) : null}
          <TextInput
            label={t('cloneSubject')}
            hint={t('cloneSubjectHint')}
            value={subject}
            maxLength={60}
            onChange={(event) => setSubject(event.target.value)}
          />
          <label className="flex cursor-pointer items-start gap-2 text-xs leading-relaxed">
            <input
              type="checkbox"
              checked={consented}
              onChange={(event) => setConsented(event.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
            />
            {t('cloneConsent')}
          </label>
          <label className="inline-flex cursor-pointer items-center gap-1.5 self-start rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs text-muted hover:text-text focus-within:outline-2">
            {uploading ? <Spinner className="size-3.5" /> : null}
            {draft.sampleAssetId ? t('replaceSample') : t('uploadSample')}
            <input
              type="file"
              accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/webm,audio/ogg"
              className="sr-only"
              disabled={uploading}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadSample(file);
                event.target.value = '';
              }}
            />
          </label>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <Select
          label={tVariants('ageStageLabel')}
          value={draft.ageStage}
          onChange={(event) => set({ ageStage: event.target.value })}
          options={[
            { value: '', label: tVariants('ageStageNone') },
            ...keysOf(AGE_STAGES).map((key) => ({
              value: key,
              label: tVariants(AGE_STAGES[key].labelKey),
            })),
          ]}
        />
        <Select
          label={t('voiceUseLabel')}
          value={draft.use}
          onChange={(event) => set({ use: event.target.value })}
          options={[
            { value: '', label: t('voiceUseNone') },
            ...VOICE_USES.map((value) => ({ value, label: t(`voiceUse.${value}`) })),
          ]}
        />
      </div>
      <TextInput
        label={t('voiceAttributeEmotion')}
        hint={t('voiceAttributeEmotionHint')}
        value={draft.attributeEmotion}
        maxLength={20}
        onChange={(event) => set({ attributeEmotion: event.target.value })}
      />
      <CustomAttributesEditor rows={draft.custom} onChange={(custom) => set({ custom })} />
      <TextArea
        label={t('voiceDescription')}
        value={draft.description}
        maxLength={500}
        className="min-h-16"
        onChange={(event) => set({ description: event.target.value })}
      />
      <TextInput
        label={t('previewText')}
        hint={t('previewTextHint')}
        value={draft.previewText}
        maxLength={MAX_PREVIEW_TEXT_LENGTH}
        onChange={(event) => set({ previewText: event.target.value })}
      />
      {error ? <ErrorNotice title={error} /> : null}
      <Button type="submit" size="sm" className="self-start" loading={busy} disabled={!ready}>
        {submitLabel}
      </Button>
    </form>
  );
}
