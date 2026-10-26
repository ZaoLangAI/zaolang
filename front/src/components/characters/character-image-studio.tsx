'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { CollapsibleSection } from '@/components/studio/collapsible-section';
import { GenerationStudioShell } from '@/components/studio/generation-studio-shell';
import { GenerationVersionHistory } from '@/components/studio/generation-version-history';
import { promptFromVersion } from '@/components/studio/generation-version-select';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptComposer } from '@/components/studio/prompt-composer';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { studioSubmitBusy, studioSubmitLabelKey } from '@/components/studio/studio-submit-busy';
import {
  KNOWN_PRESET_KEYS,
  MAX_APPLIED_SKILLS,
  useStyleAndSkillPicker,
} from '@/components/studio/style-and-skill-picker';
import { Button } from '@/components/ui/button';
import { Field, Select, TextInput } from '@/components/ui/field';
import {
  IconCheck,
  IconLandscape,
  IconPortrait,
  IconSparkle,
  IconUser,
} from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import {
  AGE_STAGES,
  CHARACTER_EXPRESSIONS,
  MAX_CHARACTER_EXPRESSIONS,
  MAX_OUTFIT_LABEL_LENGTH,
  type AgeStage,
  type CharacterExpression,
  keysOf,
} from '@/features/image-assets/vocabulary';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type {
  AssetEntry,
  AssetVariant,
  Character,
  CreationSkillSummary,
  GenerationJob,
  QualityTier,
} from '@/lib/api/types';
import { characterHeroUrl, characterSheetAsset } from '@/lib/characters';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import type { Asset } from '@/lib/upload';
import { useGenerationModels } from '@/lib/use-generation-models';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useJobStream } from '@/lib/use-job-stream';

export type CharacterGender = 'male' | 'female' | 'other';
type CharacterImageMode = 'portrait' | 'sheet' | 'expressions' | 'outfit';
type CharacterViewChoice = 'front' | 'side' | 'back';
type Orientation = 'portrait' | 'landscape';

const CHARACTER_VIEWS: readonly CharacterViewChoice[] = ['front', 'side', 'back'] as const;
const GENDER_KEYS: readonly CharacterGender[] = ['male', 'female', 'other'] as const;
const PERSONALITY_PRESETS = [
  'cold',
  'gentle',
  'tsundere',
  'calm',
  'lively',
  'scheming',
  'passionate',
  'mysterious',
] as const;

const PORTRAIT_ASPECTS = ['3:4', '9:16', '2:3', '1:1'] as const;
const LANDSCAPE_ASPECTS = ['16:9', '4:3', '3:2'] as const;
const ALL_ASPECTS = [...PORTRAIT_ASPECTS, ...LANDSCAPE_ASPECTS] as const;

function initialReferenceUploads(character?: Character | null): Asset[] {
  if (!character) return [];
  const hero = characterSheetAsset(character);
  if (!hero?.url) return [];
  return [
    {
      id: hero.asset_id,
      media_type: 'image',
      mime_type: 'image/jpeg',
      size_bytes: 0,
      url: hero.url,
      role: 'reference',
      moderation_status: 'approved',
      created_at: hero.created_at ?? character.updated_at,
      updated_at: hero.created_at ?? character.updated_at,
      is_prototype: false,
      ai_generated: true,
      depicts_real_person: false,
    } as unknown as Asset,
  ];
}

export function buildCharacterProfilePrefix({
  gender,
  age,
  personality,
  genderLabel,
  ageLabel,
  personalityPrefix,
}: {
  gender: CharacterGender | null;
  age: AgeStage | null;
  personality: string;
  genderLabel?: string;
  ageLabel?: string;
  personalityPrefix: string;
}): string {
  const parts: string[] = [];
  if (gender && genderLabel) parts.push(genderLabel);
  if (age && ageLabel) parts.push(ageLabel);
  const cleanPersonality = personality.trim();
  if (cleanPersonality) parts.push(`${personalityPrefix}${cleanPersonality}`);
  return parts.join('，');
}

function CharacterImageResultStage({
  job,
  isRunning,
  submitting,
  confirming,
  confirmedJobId,
  isEdit,
  onConfirmUseImage,
  existingHeroUrl,
}: {
  job: GenerationJob | null;
  isRunning: boolean;
  submitting: boolean;
  confirming: boolean;
  confirmedJobId: string | null;
  isEdit: boolean;
  onConfirmUseImage: (job: GenerationJob) => void;
  existingHeroUrl: string | null;
}) {
  const t = useTranslations('characters');
  const tRemix = useTranslations('remixPage');
  const [outputUrls, setOutputUrls] = useState<Record<string, string>>({});
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);

  const outputAssetIds = useMemo(() => {
    if (!job) return [];
    const list = job.output_asset_ids ?? [];
    if (list.length > 0) return list;
    return job.output_asset_id ? [job.output_asset_id] : [];
  }, [job]);

  useEffect(() => {
    if (!job || job.status !== 'succeeded') return;
    let cancelled = false;
    const loadUrls = async () => {
      const next: Record<string, string> = {};
      if (job.output_asset_id && job.output_url) {
        next[job.output_asset_id] = job.output_url;
      }
      for (const assetId of outputAssetIds) {
        if (next[assetId]) continue;
        const url = await refreshAssetUrl(assetId);
        if (url) next[assetId] = url;
      }
      if (!cancelled) {
        setOutputUrls(next);
        setSelectedAssetId((prev) =>
          prev && outputAssetIds.includes(prev) ? prev : (outputAssetIds[0] ?? null),
        );
      }
    };
    void loadUrls();
    return () => {
      cancelled = true;
    };
  }, [job, outputAssetIds]);

  const activeAssetId =
    selectedAssetId && outputAssetIds.includes(selectedAssetId)
      ? selectedAssetId
      : (outputAssetIds[0] ?? null);
  const activeUrl =
    (activeAssetId ? outputUrls[activeAssetId] : null) ?? job?.output_url ?? existingHeroUrl;
  const isConfirmed = Boolean(job && confirmedJobId === job.id);

  const handleImageError = useCallback(async () => {
    if (!job) return;
    if (activeAssetId) {
      const fresh = await refreshAssetUrl(activeAssetId);
      if (fresh) {
        setOutputUrls((prev) => ({ ...prev, [activeAssetId]: fresh }));
        return;
      }
    }
    const freshJobUrl = await refreshJobOutputUrl(job.id);
    if (freshJobUrl && activeAssetId) {
      setOutputUrls((prev) => ({ ...prev, [activeAssetId]: freshJobUrl }));
    }
  }, [activeAssetId, job]);

  if (submitting || isRunning) {
    const progress = Math.max(5, Math.min(99, job?.progress ?? 12));
    return (
      <div className="flex aspect-[4/3] flex-col items-center justify-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-6 text-center">
        <Spinner />
        <p className="text-sm font-medium text-text">{t('studioGeneratingTitle')}</p>
        <p className="text-xs text-muted">{job?.progress ? `${job.progress}%` : t('studioGeneratingTitle')}</p>
        <div className="h-1.5 w-48 overflow-hidden rounded-full bg-surface">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    );
  }

  if (job?.status === 'failed') {
    return (
      <div
        role="alert"
        className="flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-danger/30 bg-danger/10 p-6 text-center"
      >
        <p className="text-sm font-medium text-danger">
          {job.failure_message || t('studioRetryHint')}
        </p>
        <p className="text-xs text-muted">{t('studioRetryHint')}</p>
      </div>
    );
  }

  if (job?.status === 'succeeded' && activeUrl) {
    return (
      <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3">
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
          <Image
            src={activeUrl}
            alt={t('studioResultAlt')}
            fill
            sizes="(min-width: 1024px) 640px, 100vw"
            className="object-contain"
            onError={() => {
              void handleImageError();
            }}
          />
        </div>

        {outputAssetIds.length > 1 ? (
          <div className="flex flex-wrap items-center gap-2">
            {outputAssetIds.map((assetId, idx) => {
              const thumb = outputUrls[assetId];
              const active = assetId === activeAssetId;
              return (
                <button
                  key={assetId}
                  type="button"
                  onClick={() => setSelectedAssetId(assetId)}
                  className={cn(
                    'relative size-14 overflow-hidden rounded-[var(--radius-sm)] border transition-colors',
                    active ? 'border-primary ring-2 ring-primary/30' : 'border-border',
                  )}
                >
                  {thumb ? (
                    <Image src={thumb} alt="" fill sizes="56px" className="object-cover" />
                  ) : (
                    <span className="text-xs text-muted">{idx + 1}</span>
                  )}
                </button>
              );
            })}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-primary/25 bg-primary/10 px-3.5 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-text">
              {isConfirmed ? t('studioConfirmedBanner') : t('studioConfirmReadyTitle')}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">{t('studioConfirmReadyHint')}</p>
          </div>
          <Button
            size="sm"
            variant={isConfirmed ? 'secondary' : 'primary'}
            loading={confirming}
            onClick={() => onConfirmUseImage(job)}
            icon={<IconCheck className="size-4" />}
          >
            {isConfirmed
              ? t('studioConfirmedAction')
              : isEdit
                ? t('studioConfirmUpdateAction')
                : t('studioConfirmCreateAction')}
          </Button>
        </div>
      </div>
    );
  }

  if (existingHeroUrl) {
    return (
      <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
          <Image
            src={existingHeroUrl}
            alt={t('studioCurrentImageAlt')}
            fill
            sizes="(min-width: 1024px) 640px, 100vw"
            className="object-contain"
          />
        </div>
        <p className="text-center text-xs text-muted">{t('studioCurrentImageHint')}</p>
      </div>
    );
  }

  return (
    <div className="flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border bg-surface-soft p-6 text-center text-muted">
      <IconUser className="size-8" />
      <p className="text-sm font-medium text-text">{t('studioEmptyPreviewTitle')}</p>
      <p className="max-w-md text-xs leading-relaxed">{t('studioEmptyPreviewBody')}</p>
    </div>
  );
}

/**
 * Visual Character Skill Component Bar (`角色技能组件栏`):
 * Surfaces character-category templates/recipes and image-capable style skills
 * as one-click visual pills right above the prompt composer, complementing
 * `@` mention and the full style/skill picker.
 */
function CharacterSkillComponentBar({
  skills,
  appliedSkillIds,
  onApplySkill,
}: {
  skills: CreationSkillSummary[];
  appliedSkillIds: string[];
  onApplySkill: (skill: CreationSkillSummary) => void;
}) {
  const t = useTranslations('characters');
  const featuredSkills = useMemo(
    () =>
      skills
        .filter(
          (s) => s.category === 'character' || s.category === 'style' || s.category === 'format',
        )
        .slice(0, 8),
    [skills],
  );

  if (featuredSkills.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <IconSparkle className="size-3.5 text-primary" />
          <span className="text-xs font-semibold text-text">{t('skillComponentBarTitle')}</span>
          <span className="text-[11px] text-muted">
            ({appliedSkillIds.length}/{MAX_APPLIED_SKILLS})
          </span>
        </div>
        <span className="text-[11px] text-muted">{t('skillComponentBarHint')}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {featuredSkills.map((skill) => {
          const active = appliedSkillIds.includes(skill.id);
          return (
            <button
              key={skill.id}
              type="button"
              disabled={active}
              onClick={() => onApplySkill(skill)}
              title={skill.description || skill.title}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                active
                  ? 'border-primary bg-primary/15 font-medium text-primary'
                  : 'border-border bg-surface-soft text-text hover:border-border-strong',
              )}
            >
              <span>@{skill.title}</span>
              {active ? <IconCheck className="size-3" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CharacterImageStudio({
  character,
  initialStyleSkillId,
  onConfirmed,
  onCancel,
}: {
  /** Provided when editing an existing character's image & profile; omitted when creating a new character. */
  character?: Character | null;
  initialStyleSkillId?: string | null;
  onConfirmed: (character: Character) => void;
  onCancel?: () => void;
}) {
  const t = useTranslations('characters');
  const tRemix = useTranslations('remixPage');
  const tPreset = useTranslations('remixPage.presets');
  const tActions = useTranslations('actions');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const isEdit = Boolean(character);

  // ---- 4 user-maintained character fields ---------------------------------
  const [name, setName] = useState(character?.name ?? '');
  const [gender, setGender] = useState<CharacterGender | null>(
    (character?.gender as CharacterGender | null) ?? null,
  );
  const [age, setAge] = useState<AgeStage | null>((character?.age as AgeStage | null) ?? null);
  const [personality, setPersonality] = useState(character?.personality ?? '');

  // Read-only base prompt on the character card (updated only on confirmation).
  const [readOnlyPrompt, setReadOnlyPrompt] = useState(character?.description ?? '');

  // ---- Studio prompt & uploads --------------------------------------------
  const [prompt, setPrompt] = useState(character?.description ?? '');
  const [uploads, setUploads] = useState<Asset[]>(() => initialReferenceUploads(character));
  const [imageMode, setImageMode] = useState<CharacterImageMode>('portrait');
  const [selectedViews, setSelectedViews] = useState<CharacterViewChoice[]>([
    'front',
    'side',
    'back',
  ]);
  const [expressions, setExpressions] = useState<CharacterExpression[]>(['neutral', 'smile']);
  const [outfitLabel, setOutfitLabel] = useState('');
  const [aspectRatio, setAspectRatio] = useState<string>('3:4');
  const [qualityTier, setQualityTier] = useState<QualityTier>('standard');
  const [forcedModel, setForcedModel] = useState('');
  const [rightsConfirmed, setRightsConfirmed] = useState(true);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});

  // ---- Polish & Job state -------------------------------------------------
  const [polishCloseSignal, setPolishCloseSignal] = useState(0);
  const [polishPending, setPolishPending] = useState(false);
  const [polishBlocked, setPolishBlocked] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobSeed, setActiveJobSeed] = useState<GenerationJob | null>(null);
  const [knownJobsById, setKnownJobsById] = useState<Record<string, GenerationJob>>({});
  const [latestJobPrompt, setLatestJobPrompt] = useState<string>('');
  const [confirmedJobId, setConfirmedJobId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);

  const nameInputRef = useRef<HTMLInputElement | null>(null);

  const operation = uploads.length > 0 ? 'image_to_image' : 'text_to_image';
  const orientation: Orientation = (LANDSCAPE_ASPECTS as readonly string[]).includes(aspectRatio)
    ? 'landscape'
    : 'portrait';
  const aspectOptions = orientation === 'landscape' ? LANDSCAPE_ASPECTS : PORTRAIT_ASPECTS;

  const applyParams = useCallback((params: Record<string, unknown>) => {
    const candidateAspect = params.aspect_ratio;
    if (
      typeof candidateAspect === 'string' &&
      (ALL_ASPECTS as readonly string[]).includes(candidateAspect)
    ) {
      setAspectRatio(candidateAspect);
    }
    const promptSuffix = params.prompt_suffix;
    if (typeof params.prompt === 'string' && params.prompt.trim()) {
      setPrompt(params.prompt);
    } else if (typeof promptSuffix === 'string' && promptSuffix.trim()) {
      setPrompt((current) => (current.trim() ? `${current}，${promptSuffix}` : promptSuffix));
    }
    const extra = Object.fromEntries(
      Object.entries(params).filter(([key]) => !KNOWN_PRESET_KEYS.has(key)),
    );
    if (Object.keys(extra).length > 0) {
      setPresetExtra((current) => ({ ...current, ...extra }));
    }
  }, []);

  // ---- Style & Character Skill components ---------------------------------
  const {
    node: styleAndSkillPicker,
    appliedSkillIds,
    appliedStyleGalleryId,
    styleHint,
    skills,
    mentionableSkills,
    applySkill,
    chips: appliedSkillChips,
    unlockDialog,
  } = useStyleAndSkillPicker({
    operation,
    onApplyParams: applyParams,
    showCreationSkillSelect: true,
    seedSkillId: initialStyleSkillId ?? undefined,
  });

  // ---- Models & Quote -----------------------------------------------------
  const modelOptions = useGenerationModels(operation);

  const handleOrientationChange = (next: Orientation) => {
    const nextRatio = next === 'landscape' ? LANDSCAPE_ASPECTS[0] : PORTRAIT_ASPECTS[0];
    setAspectRatio(nextRatio);
  };

  // ---- Profile context synthesis ------------------------------------------
  const profileContextText = useMemo(
    () =>
      buildCharacterProfilePrefix({
        gender,
        age,
        personality,
        genderLabel: gender ? t(`genderOptions.${gender}`) : undefined,
        ageLabel: age ? tPreset(AGE_STAGES[age].labelKey) : undefined,
        personalityPrefix: t('personalityPrefix'),
      }),
    [age, gender, personality, t, tPreset],
  );

  const effectivePrompt = useMemo(() => {
    const cleanPrompt = prompt.trim();
    if (!profileContextText) return cleanPrompt;
    if (!cleanPrompt) return profileContextText;
    if (cleanPrompt.includes(profileContextText)) return cleanPrompt;
    return `${profileContextText}。${cleanPrompt}`;
  }, [profileContextText, prompt]);

  const togglePersonalityPreset = (presetKey: (typeof PERSONALITY_PRESETS)[number]) => {
    const label = t(`personalityPresets.${presetKey}`);
    const tokens = personality
      .split(/[、，,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const next = tokens.includes(label)
      ? tokens.filter((item) => item !== label)
      : [...tokens, label];
    setPersonality(next.join('、'));
  };

  const toggleCharacterView = (view: CharacterViewChoice) => {
    setSelectedViews((current) => {
      if (current.includes(view)) {
        return current.length > 1 ? current.filter((v) => v !== view) : current;
      }
      return CHARACTER_VIEWS.filter((v) => current.includes(v) || v === view);
    });
  };

  const toggleExpression = (expr: CharacterExpression) => {
    setExpressions((current) => {
      if (current.includes(expr)) {
        return current.length > 1 ? current.filter((item) => item !== expr) : current;
      }
      if (current.length >= MAX_CHARACTER_EXPRESSIONS) return current;
      return [...current, expr];
    });
  };

  // ---- Job stream & version history ---------------------------------------
  const { job: liveJob } = useJobStream(activeJobId ?? '', activeJobSeed);
  const displayJob = liveJob && liveJob.id === activeJobId ? liveJob : activeJobSeed;

  const knownJobs = useMemo(() => {
    const map = { ...knownJobsById };
    if (displayJob) map[displayJob.id] = displayJob;
    return Object.values(map);
  }, [displayJob, knownJobsById]);

  const isRunning = Boolean(
    displayJob &&
    (displayJob.status === 'queued' ||
      displayJob.status === 'running' ||
      displayJob.status === 'awaiting_input'),
  );

  const selectVersion = useCallback((job: GenerationJob) => {
    setActiveJobId(job.id);
    setActiveJobSeed(job);
    const verPrompt = promptFromVersion(job);
    if (verPrompt) {
      setPrompt(verPrompt);
      setLatestJobPrompt(verPrompt);
    }
  }, []);

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    {
      operation,
      qualityTier,
      durationSeconds: 5,
      assetKind: 'character',
      characterViews: imageMode === 'sheet' ? selectedViews : undefined,
    },
    {
      label: t('studioGenerateCharacterImage'),
      onSubmitted: (job) => {
        setDraftId((curr) => job.draft_id ?? curr);
        setActiveJobId(job.id);
        setActiveJobSeed(job);
        setKnownJobsById((curr) => ({ ...curr, [job.id]: job }));
        setLatestJobPrompt(effectivePrompt.trim());
        setConfirmedJobId(null);
      },
    },
  );

  const handleSubmit = () => {
    setPolishCloseSignal((n) => n + 1);
    const finalPrompt = effectivePrompt.trim();
    if (!finalPrompt) return;

    submit({
      operation,
      qualityTier,
      durationSeconds: 5,
      prompt: finalPrompt,
      aspectRatio,
      referenceAssetIds: uploads.map((a) => a.id),
      assetKind: 'character',
      characterViews: imageMode === 'sheet' ? selectedViews : undefined,
      targetCharacterId: character?.id ?? null,
      subjectNameHint: name.trim() || undefined,
      autoAttachAsset: false,
      assetPresets: {
        character_portrait: imageMode === 'portrait',
        character_expressions: imageMode === 'expressions' ? expressions : null,
        character_outfit_label:
          imageMode === 'outfit' && outfitLabel.trim() ? outfitLabel.trim() : null,
      },
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      forcedModel: forcedModel || undefined,
      draftId: draftId ?? undefined,
      draftTitle: (name.trim() || finalPrompt || t('studioDefaultDraftTitle')).slice(0, 60),
      extra: presetExtra,
    });
  };

  // ---- Confirm & Use Generated Image (creates/updates character & prompt) -
  const handleConfirmUseImage = async (job: GenerationJob) => {
    const cleanName = name.trim();
    if (!cleanName) {
      notify(t('nameRequiredForConfirm'), 'error');
      nameInputRef.current?.focus();
      return;
    }
    const outputIds =
      job.output_asset_ids && job.output_asset_ids.length > 0
        ? job.output_asset_ids
        : job.output_asset_id
          ? [job.output_asset_id]
          : [];
    if (outputIds.length === 0) {
      notify(t('unavailable'), 'error');
      return;
    }

    const confirmedPrompt = (latestJobPrompt || effectivePrompt).trim();
    setConfirming(true);
    try {
      let targetChar: Character;
      if (character) {
        targetChar = await api.patch<Character>(`/v1/characters/${character.id}`, {
          name: cleanName,
          gender,
          age,
          personality: personality.trim() || null,
          description: confirmedPrompt || null,
        });
      } else {
        targetChar = await api.post<Character>('/v1/characters', {
          name: cleanName,
          gender,
          age,
          personality: personality.trim() || null,
          description: confirmedPrompt || null,
          source: 'library',
        });
      }

      // Resolve target look (default look or named outfit look).
      const looks = targetChar.looks ?? [];
      let targetLook: AssetVariant | undefined = looks.find((l) => l.is_default) ?? looks[0];

      if (imageMode === 'outfit' && outfitLabel.trim()) {
        const cleanOutfit = outfitLabel.trim();
        const existingOutfit = looks.find((l) => l.name === cleanOutfit);
        targetLook =
          existingOutfit ??
          (await api.post<AssetVariant>(`/v1/characters/${targetChar.id}/looks`, {
            name: cleanOutfit,
          }));
      }

      if (targetLook) {
        // Demote existing approved entries in the same slot so the newly
        // confirmed image cleanly takes over as the slot's approved image.
        const existingEntries = targetLook.entries ?? [];
        for (const oldEntry of existingEntries) {
          if (oldEntry.status !== 'approved') continue;
          const samePortrait =
            imageMode === 'portrait' && oldEntry.entry_type === 'identity_portrait';
          const sameSheet =
            (imageMode === 'sheet' || imageMode === 'outfit') &&
            oldEntry.entry_type === 'character_sheet';
          if (samePortrait || sameSheet) {
            await api.patch(`/v1/characters/${targetChar.id}/entries/${oldEntry.id}`, {
              status: 'candidate',
            });
          }
        }

        if (imageMode === 'portrait') {
          const entry = await api.post<AssetEntry>(
            `/v1/characters/${targetChar.id}/looks/${targetLook.id}/entries`,
            {
              asset_id: outputIds[0],
              entry_type: 'identity_portrait',
            },
          );
          await api.post(`/v1/characters/${targetChar.id}/entries/${entry.id}:anchor`);
        } else if (imageMode === 'expressions') {
          await api.post<AssetEntry>(
            `/v1/characters/${targetChar.id}/looks/${targetLook.id}/entries`,
            {
              asset_id: outputIds[0],
              entry_type: 'expression_sheet',
              expressions,
            },
          );
        } else {
          // sheet or outfit
          for (let i = 0; i < outputIds.length; i += 1) {
            const viewChoice = selectedViews[i] ?? 'front';
            const isFront = i === 0 || viewChoice === 'front';
            const entry = await api.post<AssetEntry>(
              `/v1/characters/${targetChar.id}/looks/${targetLook.id}/entries`,
              {
                asset_id: outputIds[i],
                entry_type: isFront ? 'character_sheet' : 'view',
                view: viewChoice,
              },
            );
            if (i === 0 && targetLook.is_default) {
              await api.post(`/v1/characters/${targetChar.id}/entries/${entry.id}:anchor`);
            }
          }
        }
      }

      const refreshed = await api.get<Character>(`/v1/characters/${targetChar.id}`);
      setReadOnlyPrompt(refreshed.description ?? confirmedPrompt);
      setConfirmedJobId(job.id);
      notify(isEdit ? t('studioUpdatedToast') : t('created'), 'success');
      onConfirmed(refreshed);
    } catch (err) {
      notify(isApiError(err) ? err.message : t('unavailable'), 'error');
    } finally {
      setConfirming(false);
    }
  };

  // Save only the 4 basic profile fields without requiring a new image generation (in edit mode).
  const handleSaveBasicProfileOnly = async () => {
    if (!character) return;
    const cleanName = name.trim();
    if (!cleanName) {
      notify(t('nameRequiredForConfirm'), 'error');
      nameInputRef.current?.focus();
      return;
    }
    setSavingProfile(true);
    try {
      const updated = await api.patch<Character>(`/v1/characters/${character.id}`, {
        name: cleanName,
        gender,
        age,
        personality: personality.trim() || null,
      });
      notify(t('updated'), 'success');
      onConfirmed(updated);
    } catch (err) {
      notify(isApiError(err) ? err.message : t('unavailable'), 'error');
    } finally {
      setSavingProfile(false);
    }
  };

  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';
  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';

  const submitBusy = studioSubmitBusy({
    submitting,
    polishPending,
    jobs: [displayJob, ...knownJobs],
  });
  const submitLabelKey = studioSubmitLabelKey(submitBusy);
  const canSubmit =
    Boolean(effectivePrompt.trim()) &&
    rightsConfirmed &&
    !submitBusy &&
    !polishBlocked &&
    (quote?.sufficient ?? true);

  const existingHeroUrl = character ? characterHeroUrl(character) : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Top Studio Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-primary/15 px-2.5 py-0.5 text-xs font-medium text-primary">
              {t('studioOnlyCharacterBadge')}
            </span>
            <h2 className="text-base font-semibold text-text">
              {isEdit
                ? t('studioEditTitle', { name: character?.name ?? '' })
                : t('studioCreateTitle')}
            </h2>
          </div>
          <p className="mt-0.5 text-xs text-muted">{t('studioSubtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          {isEdit ? (
            <Button
              size="sm"
              variant="secondary"
              loading={savingProfile}
              onClick={() => void handleSaveBasicProfileOnly()}
            >
              {t('saveBasicProfileOnly')}
            </Button>
          ) : null}
          {onCancel ? (
            <Button size="sm" variant="ghost" onClick={onCancel}>
              {tActions('cancel')}
            </Button>
          ) : null}
        </div>
      </div>

      <GenerationStudioShell
        uploads={uploads}
        onUploaded={(asset) => {
          setUploads((curr) => (curr.some((a) => a.id === asset.id) ? curr : [...curr, asset]));
        }}
        onRemove={(assetId) => setUploads((curr) => curr.filter((a) => a.id !== assetId))}
        isPortraitPreview={orientation === 'portrait'}
        previewSlot={
          <div className="flex flex-col gap-3">
            <CharacterImageResultStage
              job={displayJob}
              isRunning={isRunning}
              submitting={submitting}
              confirming={confirming}
              confirmedJobId={confirmedJobId}
              isEdit={isEdit}
              onConfirmUseImage={(job) => void handleConfirmUseImage(job)}
              existingHeroUrl={existingHeroUrl}
            />

            {knownJobs.length > 0 ? (
              <GenerationVersionHistory
                jobs={knownJobs}
                activeJob={displayJob}
                draftId={draftId}
                onSelect={selectVersion}
              />
            ) : null}
          </div>
        }
        promptSlot={
          <div className="flex flex-col gap-3">
            {/* Visual Character Skill Component Bar */}
            <CharacterSkillComponentBar
              skills={skills}
              appliedSkillIds={appliedSkillIds}
              onApplySkill={applySkill}
            />

            {/* Read-only base prompt reference card */}
            {readOnlyPrompt ? (
              <div className="flex flex-wrap items-start justify-between gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft px-3.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-text">
                      {t('readOnlyImagePromptLabel')}
                    </span>
                    <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
                      {t('readOnlyBadge')}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{readOnlyPrompt}</p>
                </div>
                {prompt.trim() !== readOnlyPrompt.trim() ? (
                  <Button size="sm" variant="ghost" onClick={() => setPrompt(readOnlyPrompt)}>
                    {t('restoreBasePrompt')}
                  </Button>
                ) : null}
              </div>
            ) : null}

            {profileContextText ? (
              <div className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-primary/20 bg-primary/8 px-3 py-1.5 text-xs text-text">
                <IconSparkle className="size-3.5 shrink-0 text-primary" />
                <span>{t('profileContextAutoInjected', { context: profileContextText })}</span>
              </div>
            ) : null}

            <PromptComposer
              prompt={prompt}
              onChange={setPrompt}
              polishContext={{
                operation,
                aspectRatio,
                qualityTier,
                styleHint: [styleHint, profileContextText].filter(Boolean).join('；'),
                hasReference: uploads.length > 0,
                assetKind: 'character',
                assetPresets: {
                  character_portrait: imageMode === 'portrait',
                  character_expressions: imageMode === 'expressions' ? expressions : undefined,
                },
              }}
              onPolishAccept={(polished) => setPrompt(polished)}
              closePolishSignal={polishCloseSignal}
              onPolishBlockedChange={setPolishBlocked}
              onPolishPendingChange={setPolishPending}
              skillMention={{
                skills: mentionableSkills,
                selectedIds: appliedSkillIds,
                maxReached: appliedSkillIds.length >= 3,
                onSelect: applySkill,
              }}
              skillChips={appliedSkillChips}
              unlockDialog={unlockDialog}
              tip={{
                title: t('studioPromptTipTitle'),
                body: t('studioPromptTipBody'),
              }}
              hint={t('studioPromptConfirmNotice')}
            />
          </div>
        }
        canSubmit={canSubmit}
        submitting={Boolean(submitBusy)}
        submitLabel={submitBusy ? tRemix(submitLabelKey) : t('studioGenerateCharacterImage')}
        onSubmit={handleSubmit}
        price={price}
        estimate={estimate}
        error={error}
      >
        {/* 1. User-maintained Character Profile (4 fields: Name, Gender, Age, Personality) */}
        <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-text">{t('basicProfileSectionTitle')}</h3>
            <span className="text-[11px] text-muted">{t('basicProfileFourFieldsHint')}</span>
          </div>

          <TextInput
            ref={nameInputRef}
            label={t('nameLabel')}
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            placeholder={t('namePlaceholder')}
          />

          <OptionGroup
            label={t('genderLabel')}
            value={gender ?? ''}
            onChange={(val) => setGender((val || null) as CharacterGender | null)}
            columns={3}
            options={GENDER_KEYS.map((key) => ({
              value: key,
              label: t(`genderOptions.${key}`),
            }))}
          />

          <Select
            label={t('ageLabel')}
            value={age ?? ''}
            onChange={(e) => setAge((e.target.value || null) as AgeStage | null)}
            options={[
              { value: '', label: t('ageUnset') },
              ...keysOf(AGE_STAGES).map((stage) => ({
                value: stage,
                label: tPreset(AGE_STAGES[stage].labelKey),
              })),
            ]}
          />

          <Field label={t('personalityLabel')} hint={t('personalityHint')}>
            {({ controlId, describedBy }) => (
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-1">
                  {PERSONALITY_PRESETS.map((presetKey) => {
                    const label = t(`personalityPresets.${presetKey}`);
                    const selected = personality
                      .split(/[、，,\s]+/)
                      .map((s) => s.trim())
                      .includes(label);
                    return (
                      <button
                        key={presetKey}
                        type="button"
                        onClick={() => togglePersonalityPreset(presetKey)}
                        className={cn(
                          'rounded-full border px-2 py-0.5 text-[11px] transition-colors',
                          selected
                            ? 'border-primary bg-primary/15 font-medium text-primary'
                            : 'border-border bg-surface text-muted hover:text-text',
                        )}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <input
                  id={controlId}
                  aria-describedby={describedBy}
                  className="w-full rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-1.5 text-xs text-text placeholder:text-muted/70 transition-colors"
                  value={personality}
                  onChange={(e) => setPersonality(e.target.value)}
                  maxLength={200}
                  placeholder={t('personalityPlaceholder')}
                />
              </div>
            )}
          </Field>
        </div>

        {/* 2. Character Image Type & Function Options (Restricted to character images) */}
        <OptionGroup
          label={t('characterImageModeLabel')}
          value={imageMode}
          onChange={setImageMode}
          columns={2}
          options={[
            { value: 'portrait', label: t('imageMode.portrait') },
            { value: 'sheet', label: t('imageMode.sheet') },
            { value: 'expressions', label: t('imageMode.expressions') },
            { value: 'outfit', label: t('imageMode.outfit') },
          ]}
        />

        {imageMode === 'sheet' ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted">{t('sheetViewsLabel')}</span>
            <div className="grid grid-cols-3 gap-1.5">
              {CHARACTER_VIEWS.map((view) => {
                const active = selectedViews.includes(view);
                return (
                  <button
                    key={view}
                    type="button"
                    onClick={() => toggleCharacterView(view)}
                    className={cn(
                      'rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs font-medium transition-colors',
                      active
                        ? 'border-primary bg-primary/15 text-primary'
                        : 'border-border bg-surface-soft text-muted hover:text-text',
                    )}
                  >
                    {t(`views.${view}`)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {imageMode === 'expressions' ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted">
              {t('expressionSelectLabel', {
                count: expressions.length,
                max: MAX_CHARACTER_EXPRESSIONS,
              })}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {keysOf(CHARACTER_EXPRESSIONS).map((expr) => {
                const active = expressions.includes(expr);
                return (
                  <button
                    key={expr}
                    type="button"
                    onClick={() => toggleExpression(expr)}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition-colors',
                      active
                        ? 'border-primary bg-primary/15 font-medium text-primary'
                        : 'border-border bg-surface-soft text-muted hover:text-text',
                    )}
                  >
                    {tPreset(CHARACTER_EXPRESSIONS[expr].labelKey)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {imageMode === 'outfit' ? (
          <TextInput
            label={t('outfitNameLabel')}
            value={outfitLabel}
            onChange={(e) => setOutfitLabel(e.target.value)}
            maxLength={MAX_OUTFIT_LABEL_LENGTH}
            placeholder={t('outfitNamePlaceholder')}
          />
        ) : null}

        {/* 3. Framing & Aspect Ratio */}
        <OptionGroup
          label={tRemix('orientation')}
          value={orientation}
          onChange={handleOrientationChange}
          columns={2}
          options={[
            {
              value: 'portrait',
              label: tRemix('orientationPortrait'),
              icon: <IconPortrait className="size-3.5" />,
            },
            {
              value: 'landscape',
              label: tRemix('orientationLandscape'),
              icon: <IconLandscape className="size-3.5" />,
            },
          ]}
        />

        <OptionGroup
          label={tRemix('aspect')}
          value={aspectRatio}
          onChange={setAspectRatio}
          columns={2}
          options={aspectOptions.map((ratio) => ({ value: ratio, label: ratio }))}
        />

        {/* 4. Style & Character Skill Picker */}
        {styleAndSkillPicker}

        {/* 5. Quality & Advanced Model Settings */}
        <QualityTierField tier={qualityTier} onChange={setQualityTier} quote={quote} />

        <CollapsibleSection label={tRemix('moreSettings')}>
          {modelOptions.length > 0 ? (
            <Select
              label={tRemix('modelSelectLabel')}
              value={forcedModel}
              onChange={(e) => setForcedModel(e.target.value)}
              options={[
                { value: '', label: tRemix('modelAuto') },
                ...modelOptions.map((m) => ({ value: m.model, label: m.label })),
              ]}
            />
          ) : null}
        </CollapsibleSection>

        <RightsAndEstimate
          rightsConfirmed={rightsConfirmed}
          onRightsChange={setRightsConfirmed}
          quote={quote}
          quoteFailed={quoteFailed}
          estimate={estimate}
          price={price}
          error={error}
        />
      </GenerationStudioShell>
    </div>
  );
}
