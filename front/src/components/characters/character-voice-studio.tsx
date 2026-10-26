'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  buildCharacterProfilePrefix,
  type CharacterGender,
} from '@/components/characters/character-image-studio';
import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { Field, Select, TextArea, TextInput } from '@/components/ui/field';
import { IconCheck, IconMic, IconPlus, IconSparkle, IconTrash } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { AGE_STAGES, type AgeStage } from '@/features/image-assets/vocabulary';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type {
  AssetVariant,
  Character,
  CharacterVoice,
  GenerationModelOption,
  VoiceMatchResponse,
  VoicePreviewResponse,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';
import { refreshAssetUrl } from '@/lib/refresh-media-src';
import { declareConsent, uploadFile } from '@/lib/upload';
import { FALLBACK_VOICES, unionVoices, useGenerationModels } from '@/lib/use-generation-models';
import { useJobStream } from '@/lib/use-job-stream';

type VoiceSource = CharacterVoice['source'];
type VoiceUse = NonNullable<NonNullable<CharacterVoice['attributes']>['use']>;

const USES: readonly VoiceUse[] = ['dialogue', 'inner_monologue', 'narration'] as const;
const SAMPLE_LINE_KEYS = ['calm', 'gentle', 'passionate', 'daily'] as const;

function modelVoices(models: GenerationModelOption[], modelId: string): string[] {
  const picked = models.find((m) => m.model === modelId);
  if (picked?.voices?.length) return picked.voices;
  const all = unionVoices(models);
  return all.length ? all : [...FALLBACK_VOICES];
}

export function CharacterVoiceStudio({
  character,
  looks: looksProp,
  initialVoices,
  onCharacterUpdated,
  onVoicesChanged,
  onClose,
}: {
  character: Character;
  looks?: AssetVariant[];
  initialVoices?: CharacterVoice[];
  onCharacterUpdated?: (updated: Character) => void;
  onVoicesChanged?: (voices: CharacterVoice[]) => void;
  onClose?: () => void;
}) {
  const t = useTranslations('characters');
  const tAssetGraph = useTranslations('assetGraph');
  const tPreset = useTranslations('remixPage.presets');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const looks = useMemo(() => looksProp ?? character.looks ?? [], [character.looks, looksProp]);
  const models = useGenerationModels('audio_generation');

  const [voices, setVoices] = useState<CharacterVoice[]>(initialVoices ?? []);
  const [loadingVoices, setLoadingVoices] = useState(!initialVoices);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string | 'new'>(
    initialVoices?.[0]?.id ?? 'new',
  );

  // Read-only voice description stored on the character card.
  const [readOnlyVoicePrompt, setReadOnlyVoicePrompt] = useState(character.voice_description ?? '');

  const firstInitialVoice = initialVoices?.[0] ?? null;

  // ---- Active voice form state --------------------------------------------
  const [name, setName] = useState(() => firstInitialVoice?.name ?? t('voiceStudioDefaultName'));
  const [voicePrompt, setVoicePrompt] = useState(
    () => firstInitialVoice?.description ?? character.voice_description ?? '',
  );
  const [source, setSource] = useState<VoiceSource>(() => firstInitialVoice?.source ?? 'preset');
  const [model, setModel] = useState(() => firstInitialVoice?.model ?? '');
  const [voiceId, setVoiceId] = useState(() => firstInitialVoice?.voice ?? '');
  const [speed, setSpeed] = useState<number>(() => firstInitialVoice?.params?.speed ?? 1);
  const [emotion, setEmotion] = useState(
    () => firstInitialVoice?.params?.emotion ?? firstInitialVoice?.attributes?.emotion ?? '',
  );
  const [use, setUse] = useState<VoiceUse | ''>(
    () => firstInitialVoice?.attributes?.use ?? 'dialogue',
  );
  const [lookIds, setLookIds] = useState<string[]>(() => firstInitialVoice?.look_ids ?? []);
  const [makeDefault, setMakeDefault] = useState(() =>
    firstInitialVoice ? Boolean(firstInitialVoice.is_default) : true,
  );
  const [sampleAssetId, setSampleAssetId] = useState<string | null>(
    () => firstInitialVoice?.sample?.asset_id ?? null,
  );
  const [sampleUrl, setSampleUrl] = useState<string | null>(
    () => firstInitialVoice?.sample?.url ?? null,
  );
  const [consentChecked, setConsentChecked] = useState(() =>
    Boolean(firstInitialVoice?.sample?.asset_id),
  );
  const [uploadingSample, setUploadingSample] = useState(false);
  const [previewText, setPreviewText] = useState(
    () => firstInitialVoice?.preview_text ?? tAssetGraph('previewTextHint'),
  );
  const [matchReason, setMatchReason] = useState<string | null>(null);
  const [matching, setMatching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quote, setQuote] = useState<VoicePreviewResponse | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewAudioUrl, setPreviewAudioUrl] = useState<string | null>(
    () => firstInitialVoice?.preview?.url ?? null,
  );
  const [confirmedVoiceId, setConfirmedVoiceId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const activeVoice = useMemo(
    () =>
      selectedVoiceId === 'new' ? null : (voices.find((v) => v.id === selectedVoiceId) ?? null),
    [selectedVoiceId, voices],
  );

  // Load voices on mount if not provided.
  const loadVoices = useCallback(async () => {
    setLoadingVoices(true);
    try {
      const list = await api.get<CharacterVoice[]>(`/v1/characters/${character.id}/voices`);
      setVoices(list);
      onVoicesChanged?.(list);
      return list;
    } catch {
      return [];
    } finally {
      setLoadingVoices(false);
    }
  }, [character.id, onVoicesChanged]);

  const populateFormFromVoice = useCallback(
    (target: CharacterVoice | null, currentVoicesCount: number) => {
      setError(null);
      setMatchReason(null);
      if (!target) {
        setName(
          currentVoicesCount === 0
            ? t('voiceStudioDefaultName')
            : `${t('voiceStudioDefaultName')} ${currentVoicesCount + 1}`,
        );
        setVoicePrompt(readOnlyVoicePrompt);
        setSource('preset');
        const firstModel = models[0]?.model ?? '';
        setModel(firstModel);
        setVoiceId(modelVoices(models, firstModel)[0] ?? '');
        setSpeed(1);
        setEmotion('');
        setUse('dialogue');
        setLookIds([]);
        setMakeDefault(currentVoicesCount === 0);
        setSampleAssetId(null);
        setSampleUrl(null);
        setConsentChecked(false);
        setPreviewText(tAssetGraph('previewTextHint'));
        setPreviewAudioUrl(null);
        return;
      }
      setName(target.name);
      setVoicePrompt(target.description ?? readOnlyVoicePrompt);
      setSource(target.source);
      const nextModel = target.model ?? models[0]?.model ?? '';
      setModel(nextModel);
      setVoiceId(target.voice ?? modelVoices(models, nextModel)[0] ?? '');
      setSpeed(target.params?.speed ?? 1);
      setEmotion(target.params?.emotion ?? target.attributes?.emotion ?? '');
      setUse(target.attributes?.use ?? 'dialogue');
      setLookIds(target.look_ids ?? []);
      setMakeDefault(Boolean(target.is_default));
      setSampleAssetId(target.sample?.asset_id ?? null);
      setSampleUrl(target.sample?.url ?? null);
      setConsentChecked(Boolean(target.sample?.asset_id));
      setPreviewText(target.preview_text ?? tAssetGraph('previewTextHint'));
      setPreviewAudioUrl(target.preview?.url ?? null);
    },
    [models, readOnlyVoicePrompt, t, tAssetGraph],
  );

  useEffect(() => {
    if (initialVoices) return;
    let cancelled = false;
    void (async () => {
      const list = await loadVoices();
      if (cancelled) return;
      const first = list[0] ?? null;
      setSelectedVoiceId(first ? first.id : 'new');
      populateFormFromVoice(first, list.length);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [character.id]);

  // Ensure default model/voice is selected once models load when creating a new voice.
  if (!model && models.length > 0 && models[0]) {
    const firstModel = models[0].model;
    setModel(firstModel);
    if (!voiceId) {
      setVoiceId(modelVoices(models, firstModel)[0] ?? '');
    }
  }

  const handleSelectVoice = (id: string | 'new') => {
    setSelectedVoiceId(id);
    if (id === 'new') {
      populateFormFromVoice(null, voices.length);
    } else {
      const found = voices.find((v) => v.id === id) ?? null;
      populateFormFromVoice(found, voices.length);
    }
  };

  // Fetch preview quote when an existing voice is selected.
  useEffect(() => {
    if (!activeVoice) return;
    let cancelled = false;
    void api
      .post<VoicePreviewResponse>(
        `/v1/characters/${character.id}/voices/${activeVoice.id}:preview`,
        { dry_run: true },
      )
      .then((res) => {
        if (!cancelled) setQuote(res);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [activeVoice, character.id]);

  // Stream preview job completion so the audio player updates live!
  const { job: previewJob } = useJobStream(previewJobId ?? '', null);
  useEffect(() => {
    if (!previewJob || previewJob.status !== 'succeeded') return;
    let cancelled = false;
    void (async () => {
      const list = await loadVoices();
      if (cancelled) return;
      const updated = list.find((v) => v.id === selectedVoiceId);
      if (updated?.preview?.url) {
        setPreviewAudioUrl(updated.preview.url);
      } else if (previewJob.output_asset_id) {
        const fresh = await refreshAssetUrl(previewJob.output_asset_id);
        if (!cancelled && fresh) setPreviewAudioUrl(fresh);
      }
      setPreviewJobId(null);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadVoices, previewJob, selectedVoiceId]);

  const selectedModelOption = models.find((m) => m.model === model);
  const availableVoices = useMemo(() => modelVoices(models, model), [models, model]);
  const capabilityParams = selectedModelOption?.voice_params ?? ['speed', 'emotion'];
  const supportsSpeed = capabilityParams.includes('speed');
  const supportsEmotion = capabilityParams.includes('emotion');
  const emotionChoices = selectedModelOption?.voice_emotions ?? [];

  const profileContextText = useMemo(
    () =>
      buildCharacterProfilePrefix({
        gender: (character.gender as CharacterGender | null) ?? null,
        age: (character.age as AgeStage | null) ?? null,
        personality: character.personality ?? '',
        genderLabel: character.gender ? t(`genderOptions.${character.gender}`) : undefined,
        ageLabel: character.age ? tPreset(AGE_STAGES[character.age].labelKey) : undefined,
        personalityPrefix: t('personalityPrefix'),
      }),
    [character.age, character.gender, character.personality, t, tPreset],
  );

  const effectiveVoicePrompt = useMemo(() => {
    const clean = voicePrompt.trim();
    if (!profileContextText) return clean;
    if (!clean) return profileContextText;
    if (clean.includes(profileContextText)) return clean;
    return `${profileContextText}，${clean}`;
  }, [profileContextText, voicePrompt]);

  // ---- AI Smart Voice Match -----------------------------------------------
  const handleAiMatchVoice = async () => {
    const descToMatch = effectiveVoicePrompt.trim();
    if (!descToMatch) {
      setError(t('voiceMatchNeedDescription'));
      return;
    }
    setMatching(true);
    setError(null);
    try {
      const matched = await api.post<VoiceMatchResponse>(
        `/v1/characters/${character.id}/voices:match`,
        { voice_description: descToMatch },
      );
      setSource('preset');
      setModel(matched.model);
      setVoiceId(matched.voice);
      if (matched.params?.speed != null) setSpeed(matched.params.speed);
      setEmotion(matched.params?.emotion ?? '');
      setMatchReason(matched.reason || null);
      notify(t('voiceMatchedSuccess', { voice: matched.voice }), 'success');
    } catch (err) {
      setError(isApiError(err) ? err.message : t('unavailable'));
    } finally {
      setMatching(false);
    }
  };

  // ---- Sample upload for clone voice --------------------------------------
  const handleUploadSample = async (file: File) => {
    setUploadingSample(true);
    setError(null);
    try {
      const asset = await uploadFile(file, 'voice_sample');
      if (asset.media_type !== 'audio') {
        setError(tAssetGraph('genericError'));
        return;
      }
      if (consentChecked) {
        await declareConsent(asset.id, {
          type: 'voice',
          subject: character.name.trim() || 'speaker',
        }).catch(() => null);
      }
      setSampleAssetId(asset.id);
      setSampleUrl(asset.url ?? null);
    } catch (err) {
      setError(isApiError(err) ? err.message : t('unavailable'));
    } finally {
      setUploadingSample(false);
    }
  };

  // ---- Save / Upsert Voice helper -----------------------------------------
  const upsertVoiceRecord = async (): Promise<CharacterVoice | null> => {
    const cleanName = name.trim() || t('voiceStudioDefaultName');
    if (source === 'preset' && (!model || !voiceId)) {
      setError(tAssetGraph('genericError'));
      return null;
    }
    if (source === 'clone' && !sampleAssetId) {
      setError(tAssetGraph('cloneConsentFirst'));
      return null;
    }
    if (source === 'clone' && !consentChecked) {
      setError(tAssetGraph('cloneConsentFirst'));
      return null;
    }

    if (source === 'clone' && sampleAssetId && sampleAssetId !== activeVoice?.sample?.asset_id) {
      await declareConsent(sampleAssetId, {
        type: 'voice',
        subject: character.name.trim() || 'speaker',
      }).catch(() => null);
    }

    const paramsPayload =
      source === 'preset'
        ? {
            speed: supportsSpeed ? speed : null,
            emotion: supportsEmotion ? emotion.trim() || null : null,
          }
        : undefined;

    const attributesPayload = {
      age_stage: (character.age as AgeStage | null) ?? null,
      emotion: emotion.trim() || null,
      use: use || null,
      custom: activeVoice?.attributes?.custom ?? [],
    };

    const body = {
      name: cleanName,
      description: voicePrompt.trim() || null,
      source,
      model: source === 'preset' ? model : null,
      voice: source === 'preset' ? voiceId : null,
      params: paramsPayload,
      attributes: attributesPayload,
      sample_asset_id: source === 'clone' ? sampleAssetId : null,
      preview_text: previewText.trim() || null,
      look_ids: lookIds,
    };

    if (activeVoice) {
      return api.patch<CharacterVoice>(`/v1/characters/${character.id}/voices/${activeVoice.id}`, {
        ...body,
        make_default: makeDefault,
      });
    }
    return api.post<CharacterVoice>(`/v1/characters/${character.id}/voices`, body);
  };

  // ---- Generate Voice Preview ---------------------------------------------
  const handleGeneratePreview = async () => {
    setPreviewing(true);
    setError(null);
    try {
      const savedVoice = await upsertVoiceRecord();
      if (!savedVoice) return;
      const list = await loadVoices();
      setSelectedVoiceId(savedVoice.id);

      const res = await api.post<VoicePreviewResponse>(
        `/v1/characters/${character.id}/voices/${savedVoice.id}:preview`,
        {
          text: (previewText.trim() || tAssetGraph('previewTextHint')).slice(0, 120),
          dry_run: false,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      setQuote(res);
      if (res.job_id) {
        setPreviewJobId(res.job_id);
      }
      onVoicesChanged?.(list);
      notify(t('voicePreviewSubmittedToast'), 'success');
    } catch (err) {
      setError(isApiError(err) ? err.message : t('unavailable'));
    } finally {
      setPreviewing(false);
    }
  };

  // ---- Confirm & Use Voice (Updates character's read-only voice_description)
  const handleConfirmUseVoice = async () => {
    setSaving(true);
    setError(null);
    try {
      const savedVoice = await upsertVoiceRecord();
      if (!savedVoice) return;

      const summaryPrompt =
        effectiveVoicePrompt.trim() ||
        (savedVoice.source === 'preset'
          ? `${savedVoice.name}（${savedVoice.voice ?? ''}）`
          : savedVoice.name);

      const updatedChar = await api.patch<Character>(`/v1/characters/${character.id}`, {
        voice_description: summaryPrompt.slice(0, 500),
      });

      setReadOnlyVoicePrompt(updatedChar.voice_description ?? summaryPrompt);
      setConfirmedVoiceId(savedVoice.id);
      setSelectedVoiceId(savedVoice.id);
      await loadVoices();
      onCharacterUpdated?.(updatedChar);
      notify(t('voiceConfirmedToast'), 'success');
    } catch (err) {
      setError(isApiError(err) ? err.message : t('unavailable'));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteVoice = async (targetId: string) => {
    setDeleting(true);
    setError(null);
    try {
      await api.delete(`/v1/characters/${character.id}/voices/${targetId}`);
      const nextList = await loadVoices();
      const first = nextList[0] ?? null;
      setSelectedVoiceId(first ? first.id : 'new');
      populateFormFromVoice(first, nextList.length);
      notify(t('voiceDeletedToast'), 'success');
    } catch (err) {
      setError(isApiError(err) ? err.message : t('unavailable'));
    } finally {
      setDeleting(false);
    }
  };

  const toggleLookBinding = (lookId: string) => {
    setLookIds((curr) =>
      curr.includes(lookId) ? curr.filter((id) => id !== lookId) : [...curr, lookId],
    );
  };

  const isPreviewRunning = Boolean(
    previewJob &&
    (previewJob.status === 'queued' ||
      previewJob.status === 'running' ||
      previewJob.status === 'awaiting_input'),
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Studio Top Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-primary/15 px-2.5 py-0.5 text-xs font-medium text-primary">
              {t('voiceStudioBadge')}
            </span>
            <h2 className="text-base font-semibold text-text">
              {t('voiceStudioTitle', { name: character.name })}
            </h2>
          </div>
          <p className="mt-0.5 text-xs text-muted">{t('voiceStudioSubtitle')}</p>
        </div>
        {onClose ? (
          <Button size="sm" variant="ghost" onClick={onClose}>
            {tActions('close')}
          </Button>
        ) : null}
      </div>

      {/* 3-Column Studio Grid matching GenerationStudioShell */}
      <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[220px_minmax(0,1fr)_340px]">
        {/* Left Column: Character Context + Voice Roster */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
            <span className="text-xs font-semibold text-text">{t('basicProfileSectionTitle')}</span>
            <p className="text-sm font-medium text-text">{character.name}</p>
            {profileContextText ? (
              <p className="text-xs leading-relaxed text-muted">{profileContextText}</p>
            ) : (
              <p className="text-xs text-muted">{t('noProfileAttributesHint')}</p>
            )}
          </div>

          <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-text">{tAssetGraph('voicesTitle')}</span>
              <Button
                size="sm"
                variant="secondary"
                icon={<IconPlus className="size-3.5" />}
                onClick={() => handleSelectVoice('new')}
              >
                {tAssetGraph('newVoice')}
              </Button>
            </div>

            {loadingVoices ? (
              <div className="flex items-center justify-center py-6">
                <Spinner />
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {voices.map((v) => {
                  const active = selectedVoiceId === v.id;
                  return (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => handleSelectVoice(v.id)}
                      className={cn(
                        'flex flex-col items-start gap-0.5 rounded-[var(--radius-sm)] border px-2.5 py-2 text-left transition-colors',
                        active
                          ? 'border-primary bg-primary/12 text-text'
                          : 'border-border bg-surface-soft text-muted hover:text-text',
                      )}
                    >
                      <div className="flex w-full items-center justify-between gap-1">
                        <span className="truncate text-xs font-semibold text-text">{v.name}</span>
                        {v.is_default ? (
                          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {tAssetGraph('defaultBadge')}
                          </span>
                        ) : null}
                      </div>
                      <span className="truncate text-[11px] text-muted">
                        {v.source === 'preset'
                          ? `${v.voice ?? '—'} · ${v.params?.speed ?? 1}x`
                          : tAssetGraph('voiceClone')}
                      </span>
                    </button>
                  );
                })}
                {selectedVoiceId === 'new' ? (
                  <div className="rounded-[var(--radius-sm)] border border-dashed border-primary bg-primary/8 px-2.5 py-2 text-xs font-medium text-primary">
                    + {t('voiceStudioCreatingNew')}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {/* Center Column: Audio Preview Stage + Voice Prompt Composer */}
        <div className="flex min-w-0 flex-col gap-4">
          {/* Audio Preview Stage */}
          <div className="flex flex-col justify-between gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex size-11 items-center justify-center rounded-full bg-primary/15 text-primary">
                  <IconMic className="size-5" />
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-text">
                      {name.trim() || t('voiceStudioDefaultName')}
                    </h3>
                    <span className="rounded-full border border-border bg-surface-soft px-2 py-0.5 text-[11px] text-muted">
                      {source === 'preset'
                        ? `${voiceId || '—'} · ${speed.toFixed(1)}x`
                        : tAssetGraph('voiceClone')}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    {emotion ? `${tAssetGraph('voiceEmotionParam')}：${emotion}` : t('voiceStageReadySubtitle')}
                  </p>
                </div>
              </div>

              {activeVoice ? (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={deleting}
                  icon={<IconTrash className="size-3.5" />}
                  onClick={() => void handleDeleteVoice(activeVoice.id)}
                >
                  {tActions('delete')}
                </Button>
              ) : null}
            </div>

            {matchReason ? (
              <div className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-primary/25 bg-primary/8 px-3 py-2 text-xs text-text">
                <IconSparkle className="mt-0.5 size-3.5 shrink-0 text-primary" />
                <span>{matchReason}</span>
              </div>
            ) : null}

            {/* Audio Player or Running Spinner */}
            <div className="flex min-h-[110px] flex-col items-center justify-center gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-4">
              {isPreviewRunning || previewing ? (
                <div className="flex flex-col items-center gap-2 text-center">
                  <Spinner />
                  <p className="text-xs font-medium text-text">{t('voicePreviewGenerating')}</p>
                </div>
              ) : previewAudioUrl ? (
                <div className="flex w-full flex-col gap-2">
                  <span className="text-[11px] font-medium text-muted">
                    {t('voiceLatestPreviewLabel')}
                  </span>
                  <audio controls src={previewAudioUrl} className="w-full" />
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 text-center text-muted">
                  <IconMic className="size-6" />
                  <p className="text-xs">{t('voiceNoPreviewYet')}</p>
                </div>
              )}
            </div>

            {/* Confirm & Use Voice CTA Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-primary/25 bg-primary/10 px-3.5 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-text">
                  {confirmedVoiceId && confirmedVoiceId === activeVoice?.id
                    ? t('voiceConfirmedBanner')
                    : t('voiceConfirmBannerTitle')}
                </p>
                <p className="mt-0.5 text-[11px] text-muted">{t('voiceConfirmBannerHint')}</p>
              </div>
              <Button
                size="sm"
                variant="primary"
                loading={saving}
                icon={<IconCheck className="size-4" />}
                onClick={() => void handleConfirmUseVoice()}
              >
                {t('voiceConfirmUseAction')}
              </Button>
            </div>
          </div>

          {/* Read-only Voice Prompt Card on Character */}
          <div className="flex flex-wrap items-start justify-between gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft px-3.5 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-text">
                  {t('readOnlyVoicePromptLabel')}
                </span>
                <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
                  {t('readOnlyBadge')}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted">
                {readOnlyVoicePrompt || t('readOnlyVoicePromptEmpty')}
              </p>
            </div>
            {readOnlyVoicePrompt && voicePrompt.trim() !== readOnlyVoicePrompt.trim() ? (
              <Button size="sm" variant="ghost" onClick={() => setVoicePrompt(readOnlyVoicePrompt)}>
                {t('restoreBasePrompt')}
              </Button>
            ) : null}
          </div>

          {/* Voice Prompt & Preview Line Composer */}
          <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-primary/20 bg-gradient-to-br from-primary/8 via-surface-raised to-surface-raised p-4 shadow-raised">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-text">{t('voiceComposerTitle')}</p>
                <p className="text-xs text-muted">{t('voiceComposerSubtitle')}</p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                loading={matching}
                icon={<IconSparkle className="size-3.5" />}
                onClick={() => void handleAiMatchVoice()}
              >
                {tAssetGraph('matchVoice')}
              </Button>
            </div>

            <TextArea
              label={t('voiceCharacteristicsPromptLabel')}
              hint={t('voicePromptConfirmNotice')}
              rows={2}
              maxLength={500}
              value={voicePrompt}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setVoicePrompt(e.target.value)
              }
              placeholder={t('voiceHint')}
            />

            <Field label={tAssetGraph('previewText')}>
              {({ controlId, describedBy }) => (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap gap-1.5">
                    {SAMPLE_LINE_KEYS.map((key) => {
                      const line = t(`voiceSampleLines.${key}`);
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setPreviewText(line)}
                          className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-[11px] text-muted transition-colors hover:border-border-strong hover:text-text"
                        >
                          {t(`voiceSampleLineLabels.${key}`)}
                        </button>
                      );
                    })}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      id={controlId}
                      aria-describedby={describedBy}
                      className="min-w-0 flex-1 h-10 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 text-sm text-text placeholder:text-muted/70 transition-colors"
                      maxLength={120}
                      value={previewText}
                      onChange={(e) => setPreviewText(e.target.value)}
                      placeholder={tAssetGraph('previewTextHint')}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={previewing || isPreviewRunning}
                      icon={<IconMic className="size-4" />}
                      onClick={() => void handleGeneratePreview()}
                    >
                      {tAssetGraph('generatePreview')}
                    </Button>
                  </div>
                </div>
              )}
            </Field>
          </div>
        </div>

        {/* Right Column: Voice Parameters Aside */}
        <aside className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h3 className="text-sm font-semibold text-text">{t('voiceParamsHeading')}</h3>

          <TextInput
            label={tAssetGraph('voiceName')}
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={40}
            placeholder={tAssetGraph('voiceNamePlaceholder')}
          />

          <OptionGroup
            label={tAssetGraph('voiceSource')}
            value={source}
            onChange={setSource}
            columns={2}
            options={[
              { value: 'preset', label: tAssetGraph('voicePreset') },
              { value: 'clone', label: tAssetGraph('voiceClone') },
            ]}
          />

          {source === 'preset' ? (
            <div className="flex flex-col gap-3">
              {models.length > 0 ? (
                <Select
                  label={tAssetGraph('voiceModel')}
                  value={model}
                  onChange={(e) => {
                    const nextModel = e.target.value;
                    setModel(nextModel);
                    const nextVoices = modelVoices(models, nextModel);
                    if (!nextVoices.includes(voiceId)) {
                      setVoiceId(nextVoices[0] ?? '');
                    }
                  }}
                  options={models.map((m) => ({ value: m.model, label: m.label }))}
                />
              ) : null}

              <Select
                label={tAssetGraph('voicePick')}
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
                options={availableVoices.map((v) => ({ value: v, label: v }))}
              />

              {supportsSpeed ? (
                <label className="flex flex-col gap-1 text-xs text-muted">
                  <div className="flex justify-between">
                    <span>{tAssetGraph('voiceSpeed')}</span>
                    <span className="tabular font-medium text-text">{speed.toFixed(1)}x</span>
                  </div>
                  <input
                    type="range"
                    min={0.5}
                    max={2}
                    step={0.1}
                    value={speed}
                    onChange={(e) => setSpeed(Number(e.target.value))}
                    className="accent-[var(--primary)]"
                  />
                </label>
              ) : null}

              {supportsEmotion ? (
                emotionChoices.length > 0 ? (
                  <Select
                    label={tAssetGraph('voiceEmotionParam')}
                    value={emotion}
                    onChange={(e) => setEmotion(e.target.value)}
                    options={[
                      { value: '', label: tAssetGraph('emotionNone') },
                      ...emotionChoices.map((item) => ({ value: item, label: item })),
                    ]}
                  />
                ) : (
                  <TextInput
                    label={tAssetGraph('voiceEmotionParam')}
                    maxLength={20}
                    value={emotion}
                    onChange={(e) => setEmotion(e.target.value)}
                    placeholder={tAssetGraph('voiceAttributeEmotionHint')}
                  />
                )
              ) : null}
            </div>
          ) : (
            <div className="flex flex-col gap-2.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3">
              <label className="flex items-start gap-2 text-xs text-text">
                <input
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                  className="mt-0.5 size-4 accent-[var(--primary)]"
                />
                <span>{tAssetGraph('cloneConsent')}</span>
              </label>
              {sampleUrl ? <audio controls src={sampleUrl} className="w-full" /> : null}
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (file) void handleUploadSample(file);
                }}
              />
              <Button
                size="sm"
                variant="secondary"
                loading={uploadingSample}
                onClick={() => fileInputRef.current?.click()}
              >
                {sampleAssetId ? tAssetGraph('replaceSample') : tAssetGraph('uploadSample')}
              </Button>
            </div>
          )}

          <Select
            label={tAssetGraph('voiceUseLabel')}
            value={use}
            onChange={(e) => setUse(e.target.value as VoiceUse | '')}
            options={[
              { value: '', label: tAssetGraph('emotionNone') },
              ...USES.map((item) => ({ value: item, label: item })),
            ]}
          />

          {looks.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted">{tAssetGraph('saveVoiceLooks')}</span>
              <div className="flex flex-wrap gap-1.5">
                {looks.map((look) => {
                  const bound = lookIds.includes(look.id);
                  return (
                    <button
                      key={look.id}
                      type="button"
                      onClick={() => toggleLookBinding(look.id)}
                      className={cn(
                        'rounded-full border px-2.5 py-0.5 text-xs transition-colors',
                        bound
                          ? 'border-primary bg-primary/15 font-medium text-primary'
                          : 'border-border bg-surface-soft text-muted hover:text-text',
                      )}
                    >
                      {look.name}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-xs text-text">
            <input
              type="checkbox"
              checked={makeDefault}
              onChange={(e) => setMakeDefault(e.target.checked)}
              className="size-4 accent-[var(--primary)]"
            />
            <span>{tAssetGraph('makeDefaultVoice')}</span>
          </label>

          {error ? <ErrorNotice title={error} /> : null}

          <div className="mt-auto flex flex-col gap-2 pt-2">
            <Button
              size="lg"
              variant="primary"
              loading={saving}
              icon={<IconCheck className="size-4" />}
              onClick={() => void handleConfirmUseVoice()}
            >
              {t('voiceConfirmUseAction')}
            </Button>
          </div>
        </aside>
      </div>
    </div>
  );
}
