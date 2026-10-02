'use client';

import { useLocale, useTranslations } from 'next-intl';
import Image from 'next/image';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { CollapsibleSection } from '@/components/studio/collapsible-section';
import { GenerationStudioShell } from '@/components/studio/generation-studio-shell';
import {
  STUDIO_RESOLUTION_LABEL_KEYS,
  adaptStudioResolution,
} from '@/components/studio/generation-resolution';
import { GenerationVersionHistory } from '@/components/studio/generation-version-history';
import {
  durationFromVersion,
  promptFromVersion,
} from '@/components/studio/generation-version-select';
import { InlineVideoResult } from '@/components/studio/inline-video-result';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptComposer } from '@/components/studio/prompt-composer';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { studioSubmitBusy, studioSubmitLabelKey } from '@/components/studio/studio-submit-busy';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import {
  KNOWN_PRESET_KEYS,
  MAX_APPLIED_SKILLS,
  useStyleAndSkillPicker,
} from '@/components/studio/style-and-skill-picker';
import { Select, TextInput } from '@/components/ui/field';
import {
  IconGear,
  IconLandscape,
  IconPortrait,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type {
  Character,
  Draft,
  GenerationJob,
  Page,
  PromptEnhanceScriptSegment,
  QualityTier,
  Scene,
} from '@/lib/api/types';
import { referenceByView } from '@/lib/characters';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { useGenerationModels } from '@/lib/use-generation-models';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useJobStream } from '@/lib/use-job-stream';
import { useResource } from '@/lib/use-resource';

import {
  updateScriptContent,
  type ScriptBlock,
  type ScriptDetail,
  type ScriptDocument,
} from './api';
import { ScriptBlockRow } from './script-block';
import { locateBreakpoint } from './script-breakpoint';
import {
  applySegmentBlockTexts,
  breakpointSegmentPrompt,
  composeClipPrompt,
  displaySegmentBlocks,
  promptForBreakpointKey,
  resolveBreakpointRefs,
} from './script-prompts';
import {
  ReferenceImagePicker,
  useReferencePicks,
} from '@/components/studio/reference-image-picker';
import { defaultCharacterReferenceIds } from '@/lib/characters';
import { defaultSceneReferenceIds } from '@/lib/scenes';

type Operation = 'text_to_video' | 'image_to_video' | 'video_to_video';
type ReferenceMode = 'input_references' | 'frame_images';
type Orientation = 'landscape' | 'portrait' | 'adaptive';

const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9', '3:2'] as const;
const PORTRAIT_ASPECTS = ['9:16', '3:4', '2:3', '9:21'] as const;
const ADAPTIVE_ASPECT = 'adaptive';
const ASPECTS = [...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS, ADAPTIVE_ASPECT] as const;
const DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
const MAX_REFERENCE_SELECTION = 4;

function draftStringParam(params: Record<string, unknown> | undefined, name: string): string {
  const value = params?.[name];
  return typeof value === 'string' && value ? value : '';
}

function shootablePolishBlocks(blocks: ScriptBlock[]): PromptEnhanceScriptSegment['blocks'] {
  return blocks
    .filter(
      (block): block is ScriptBlock & { type: 'scene' | 'action' | 'camera' | 'dialogue' } =>
        block.type !== 'breakpoint',
    )
    .map((block) => ({
      type: block.type,
      character: block.character,
      text: block.text,
    }));
}

/**
 * Independent video studio for one script breakpoint. The prompt is this
 * cut's original wording; colour blocks below it stay in document order;
 * the right-hand scene control is a library dropdown (any owned scene),
 * and the cast list is the full character library.
 */
export function ScriptClipStudio({
  episodeId,
  breakpointKey,
  script,
  initialDraft,
}: {
  episodeId: string;
  breakpointKey: string;
  script: ScriptDetail;
  initialDraft?: Draft;
}) {
  const t = useTranslations('remixPage');
  const tScript = useTranslations('scriptStudio');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { status: sessionStatus } = useSession();
  const { notify } = useToast();

  const [document, setDocument] = useState<ScriptDocument>(script.script);
  const located = useMemo(
    () => locateBreakpoint(document, breakpointKey),
    [document, breakpointKey],
  );
  const shown = located
    ? displaySegmentBlocks(located.scene, located.blockIndex)
    : { environment: [], blocks: [] };
  const seedRefs = useMemo(() => {
    if (!located) {
      return {
        characterIds: [] as string[],
        sceneId: null as string | null,
        characterLooks: {} as Record<string, string>,
        sceneVariantId: null as string | null,
      };
    }
    return resolveBreakpointRefs(document, located.scene, located.blockIndex);
  }, [document, located]);

  const draftClipPrompt = draftStringParam(initialDraft?.params, 'clip_user_prompt');
  const [prompt, setPrompt] = useState(
    draftClipPrompt || promptForBreakpointKey(script.script, breakpointKey) || '',
  );
  const [aspect, setAspect] = useState<string>(() => {
    const draftAspect = initialDraft?.params?.aspect_ratio;
    return typeof draftAspect === 'string' && (ASPECTS as readonly string[]).includes(draftAspect)
      ? draftAspect
      : '16:9';
  });
  const [duration, setDuration] = useState(() => {
    const draftDuration = initialDraft?.params?.duration_seconds;
    return typeof draftDuration === 'number' && DURATIONS.includes(draftDuration)
      ? draftDuration
      : 8;
  });
  const [resolution, setResolution] = useState<'480p' | '720p' | '1080p' | '2K'>('1080p');
  const [seed, setSeed] = useState('');
  const [forcedModel, setForcedModel] = useState('');
  const [referenceMode, setReferenceMode] = useState<ReferenceMode>('input_references');
  const [firstFrameAssetId, setFirstFrameAssetId] = useState('');
  const [lastFrameAssetId, setLastFrameAssetId] = useState('');
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});
  const [selectedReferenceCharacterIds, setSelectedReferenceCharacterIds] = useState<string[]>(() =>
    seedRefs.characterIds.slice(0, MAX_REFERENCE_SELECTION),
  );
  const [selectedReferenceSceneIds, setSelectedReferenceSceneIds] = useState<string[]>(() =>
    seedRefs.sceneId ? [seedRefs.sceneId] : [],
  );
  // Which of each picked character's/scene's images to send (e.g. only the
  // 婚礼 outfit) — unset means the backend's default subset.
  // Seeded from the script's linked looks / scene variant.
  const characterRefPicks = useReferencePicks(
    Object.fromEntries(
      Object.entries(seedRefs.characterLooks).map(([id, variantId]) => [id, { variantId }]),
    ),
  );
  const sceneRefPicks = useReferencePicks(
    seedRefs.sceneId && seedRefs.sceneVariantId
      ? { [seedRefs.sceneId]: { variantId: seedRefs.sceneVariantId } }
      : {},
  );

  const [draftId, setDraftId] = useState<string | null>(initialDraft?.id ?? null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobSeed, setActiveJobSeed] = useState<GenerationJob | null>(null);
  const [appliedJobId, setAppliedJobId] = useState<string | null>(
    initialDraft?.applied_job_id ?? null,
  );
  const [linkedEpisodeId, setLinkedEpisodeId] = useState(episodeId);
  const [cancelling, setCancelling] = useState(false);
  const [polishPending, setPolishPending] = useState(false);

  const resumeDefaultJobId = initialDraft?.applied_job_id ?? initialDraft?.latest_job_id ?? null;
  const resumedJob = useResource<GenerationJob>(
    !activeJobId && resumeDefaultJobId ? `/v1/generation-jobs/${resumeDefaultJobId}` : null,
  );
  if (!activeJobId && resumedJob.status === 'ready' && resumedJob.data) {
    setActiveJobId(resumedJob.data.id);
    setActiveJobSeed(resumedJob.data);
    if (!draftClipPrompt && resumedJob.data.prompt) setPrompt(resumedJob.data.prompt);
  }

  const {
    job: liveJob,
    events: jobEvents,
    connected: jobConnected,
    reconnecting: jobReconnecting,
    liveThinking,
    applyJob,
  } = useJobStream(activeJobId ?? '', activeJobSeed);
  const displayJob = liveJob && liveJob.id === activeJobId ? liveJob : activeJobSeed;

  const [knownJobsById, setKnownJobsById] = useState<Record<string, GenerationJob>>({});
  const knownJobs = useMemo(() => Object.values(knownJobsById), [knownJobsById]);
  const draftJobsHistory = useResource<Page<GenerationJob>>(
    draftId ? `/v1/generation-jobs?draft_id=${draftId}` : null,
  );
  const historySeededRef = useRef(false);
  useEffect(() => {
    if (historySeededRef.current || !draftJobsHistory.data) return;
    historySeededRef.current = true;
    const seeded: Record<string, GenerationJob> = {};
    for (const job of draftJobsHistory.data.items) seeded[job.id] = job;
    setKnownJobsById((current) => ({ ...seeded, ...current }));
  }, [draftJobsHistory.data]);
  const lastRememberedDisplayJobRef = useRef<GenerationJob | null>(null);
  useEffect(() => {
    if (!displayJob || displayJob === lastRememberedDisplayJobRef.current) return;
    lastRememberedDisplayJobRef.current = displayJob;
    setKnownJobsById((current) => ({ ...current, [displayJob.id]: displayJob }));
  }, [displayJob]);
  // A job that just succeeded becomes the applied version. Adjusted during
  // render, once per live snapshot, rather than with a setState in an effect.
  const [autoAppliedJob, setAutoAppliedJob] = useState<GenerationJob | null>(null);
  if (liveJob?.status === 'succeeded' && liveJob.id === activeJobId && liveJob !== autoAppliedJob) {
    setAutoAppliedJob(liveJob);
    setAppliedJobId(liveJob.id);
  }

  const cancelActiveJob = async () => {
    if (!activeJobId) return;
    setCancelling(true);
    try {
      const latest = await api.post<GenerationJob>(`/v1/generation-jobs/${activeJobId}/cancel`);
      applyJob(latest);
    } catch (caught) {
      notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
    } finally {
      setCancelling(false);
    }
  };

  const selectVersion = (job: GenerationJob) => {
    setActiveJobId(job.id);
    setActiveJobSeed(job);
    const nextPrompt = promptFromVersion(job);
    if (nextPrompt) setPrompt(nextPrompt);
    const durationSeconds = durationFromVersion(job, DURATIONS);
    if (durationSeconds !== null) setDuration(durationSeconds);
  };

  const handleAppliedChange = (draft: Draft) => {
    setAppliedJobId(draft.applied_job_id ?? null);
  };

  const handleHiddenVersion = (jobId: string) => {
    setKnownJobsById((current) => {
      const next = { ...current };
      delete next[jobId];
      return next;
    });
    if (!draftId) return;
    void api
      .get<Draft>(`/v1/drafts/${draftId}`)
      .then((draft) => {
        setAppliedJobId(draft.applied_job_id ?? null);
        if (activeJobId !== jobId) return;
        const next = draft.applied_job_id
          ? knownJobs.find((job) => job.id === draft.applied_job_id)
          : undefined;
        if (next) {
          selectVersion(next);
          return;
        }
        setActiveJobId(null);
        setActiveJobSeed(null);
      })
      .catch((caught) => {
        notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
      });
  };

  const handleUseAsReference = useCallback(
    async (job: GenerationJob) => {
      if (!job.output_asset_id) return;
      try {
        const asset = await api.get<Asset>(`/v1/assets/${job.output_asset_id}`);
        setUploads((current) => [...current, asset]);
      } catch (caught) {
        notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
        return;
      }
      if (job.prompt) setPrompt(job.prompt);
    },
    [notify, tStates],
  );

  const toggleReferenceCharacter = (id: string) =>
    setSelectedReferenceCharacterIds((current) =>
      current.includes(id)
        ? current.filter((existing) => existing !== id)
        : current.length < MAX_REFERENCE_SELECTION
          ? [...current, id]
          : current,
    );
  const selectReferenceScene = (id: string) => setSelectedReferenceSceneIds(id ? [id] : []);

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
  let operation: Operation = 'text_to_video';
  if (referenceMode === 'frame_images' && firstFrameAssetId) operation = 'image_to_video';
  else if (hasVideoReference) operation = 'video_to_video';
  else if (hasImageReference) operation = 'image_to_video';

  const modelOptions = useGenerationModels(operation);
  const forcedOption = modelOptions.find((option) => option.model === forcedModel);
  const resolutionPreview = useMemo(() => {
    if (!forcedModel || !forcedOption) return null;
    return adaptStudioResolution(resolution, forcedOption.resolutions);
  }, [forcedModel, forcedOption, resolution]);
  const resolutionHint =
    resolutionPreview && resolutionPreview.kind !== 'exact'
      ? t('resolutionAdapted', {
          actual: t(STUDIO_RESOLUTION_LABEL_KEYS[resolutionPreview.studioTier]),
        })
      : forcedModel
        ? t('resolutionHint')
        : t('resolutionHintAuto');

  const charactersResource = useResource<Character[]>(
    sessionStatus === 'authenticated' ? '/v1/characters' : null,
  );
  const scenesResource = useResource<Scene[]>(
    sessionStatus === 'authenticated' ? '/v1/scenes' : null,
  );
  const characters = charactersResource.data ?? [];
  const scenes = scenesResource.data ?? [];

  const {
    node: styleAndSkillPicker,
    appliedSkillIds,
    appliedStyleGalleryId,
    styleHint,
    mentionableSkills,
    applySkill,
    chips: appliedSkillChips,
    unlockDialog,
  } = useStyleAndSkillPicker({
    operation,
    onApplyParams: applyParams,
    showCreationSkillSelect: false,
  });

  const orientation: Orientation =
    aspect === ADAPTIVE_ASPECT
      ? 'adaptive'
      : (LANDSCAPE_ASPECTS as readonly string[]).includes(aspect)
        ? 'landscape'
        : 'portrait';
  const aspectOptions: readonly string[] =
    orientation === 'landscape'
      ? LANDSCAPE_ASPECTS
      : orientation === 'portrait'
        ? PORTRAIT_ASPECTS
        : [];
  const imageUploads = uploads.filter((asset) => asset.media_type === 'image');
  const parsedSeed = seed.trim() ? Number(seed) : undefined;
  const seedValid =
    parsedSeed === undefined ||
    (Number.isInteger(parsedSeed) && parsedSeed >= 0 && parsedSeed <= 2 ** 31 - 1);

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation, qualityTier: tier, durationSeconds: duration },
    {
      label: t('submit'),
      onSubmitted: (job) => {
        setDraftId(job.draft_id ?? draftId);
        setActiveJobId(job.id);
        setActiveJobSeed(job);
      },
    },
  );

  const frameSelectionValid = referenceMode !== 'frame_images' || Boolean(firstFrameAssetId);
  const busy = studioSubmitBusy({
    submitting,
    polishPending,
    jobs: [displayJob, ...knownJobs],
  });
  const canSubmit =
    prompt.trim().length > 0 &&
    Boolean(located) &&
    rightsConfirmed &&
    frameSelectionValid &&
    seedValid &&
    !busy &&
    (quote?.sufficient ?? true);

  const removeUpload = (assetId: string) => {
    setUploads((current) => current.filter((asset) => asset.id !== assetId));
    if (firstFrameAssetId === assetId) setFirstFrameAssetId('');
    if (lastFrameAssetId === assetId) setLastFrameAssetId('');
  };

  const runSubmit = () => {
    if (busy || !located) return;
    const labeled = breakpointSegmentPrompt(located.scene, located.blockIndex);
    submit({
      operation,
      qualityTier: tier,
      durationSeconds: duration,
      prompt: composeClipPrompt(prompt, labeled),
      aspectRatio: aspect,
      seed: parsedSeed,
      referenceAssetIds: referenceMode === 'frame_images' ? [] : uploads.map((asset) => asset.id),
      videoOptions: {
        resolution,
        reference_mode: referenceMode,
        first_frame_asset_id: referenceMode === 'frame_images' ? firstFrameAssetId || null : null,
        last_frame_asset_id: referenceMode === 'frame_images' ? lastFrameAssetId || null : null,
      },
      extra: { sound, ...presetExtra },
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      characterIds: selectedReferenceCharacterIds,
      sceneIds: selectedReferenceSceneIds,
      assetPresets: {
        character_ref_selection: characterRefPicks
          .selectionFor(selectedReferenceCharacterIds)
          .map(({ ownerId, ...pick }) => ({ character_id: ownerId, ...pick })),
        scene_ref_selection: sceneRefPicks
          .selectionFor(selectedReferenceSceneIds)
          .map(({ ownerId, ...pick }) => ({ scene_id: ownerId, ...pick })),
      },
      maxCredits: quote?.credits,
      draftTitle: located.scene.heading || script.title || null,
      draftId: draftId ?? undefined,
      linkEpisodeId: episodeId,
      linkBreakpointKey: breakpointKey,
      forcedModel: forcedModel || undefined,
      draftParams: { clip_user_prompt: prompt.trim() },
    });
  };

  const handlePolishAccept = (nextPrompt: string, segment?: PromptEnhanceScriptSegment) => {
    setPrompt(nextPrompt);
    if (!segment) return;
    const next = applySegmentBlockTexts(document, breakpointKey, segment.blocks);
    if (!next) return;
    setDocument(next);
    void updateScriptContent(episodeId, next)
      .then((saved) => setDocument(saved))
      .catch((caught) => {
        notify(isApiError(caught) ? caught.message : tScript('clipPolishSyncFailed'), 'error');
      });
  };

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const selectedScene = scenes.find((scene) => scene.id === selectedReferenceSceneIds[0]);

  const paramsPanel = (
    <>
      {styleAndSkillPicker}

      <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border p-3">
        <p className="text-xs text-muted">{t('referenceCastLabel')}</p>
        <p className="text-[11px] text-muted">{tScript('clipRefsHint')}</p>
        {characters.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {characters.map((character) => {
              const checked = selectedReferenceCharacterIds.includes(character.id);
              const disabled =
                !checked && selectedReferenceCharacterIds.length >= MAX_REFERENCE_SELECTION;
              const thumbnailUrl = referenceByView(character, 'front')?.url;
              return (
                <li key={character.id}>
                  <label
                    className={cn(
                      'flex items-center gap-2.5 text-sm',
                      disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggleReferenceCharacter(character.id)}
                      className="size-4 shrink-0 accent-[var(--primary)]"
                    />
                    <span className="relative size-7 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                      {thumbnailUrl ? (
                        <Image
                          src={thumbnailUrl}
                          alt=""
                          fill
                          sizes="28px"
                          className="object-cover"
                        />
                      ) : null}
                    </span>
                    {character.name}
                  </label>
                  {checked ? (
                    <ReferenceImagePicker
                      label={t('referencePickLabel', { name: character.name })}
                      variants={character.looks ?? []}
                      defaultAssetIds={defaultCharacterReferenceIds(character)}
                      value={characterRefPicks.picks[character.id]}
                      onChange={(pick) => characterRefPicks.set(character.id, pick)}
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-xs text-muted">
            {t('referenceCastEmpty')}{' '}
            <Link href="/create/characters" className="text-primary hover:underline">
              {t('manageCharactersLink')}
            </Link>
          </p>
        )}

        <Select
          label={t('referenceScenesLabel')}
          value={selectedReferenceSceneIds[0] ?? ''}
          onChange={(event) => selectReferenceScene(event.target.value)}
          options={[
            { value: '', label: tScript('clipSceneNone') },
            ...scenes.map((scene) => ({ value: scene.id, label: scene.name })),
          ]}
        />
        {selectedScene ? (
          <ReferenceImagePicker
            label={t('referencePickLabel', { name: selectedScene.name })}
            variants={selectedScene.variants ?? []}
            defaultAssetIds={defaultSceneReferenceIds(selectedScene)}
            value={sceneRefPicks.picks[selectedScene.id]}
            onChange={(pick) => sceneRefPicks.set(selectedScene.id, pick)}
          />
        ) : null}
        <Link href="/create/scenes" className="text-[11px] text-muted hover:text-text">
          {t('manageScenesLink')}
        </Link>
        {selectedReferenceCharacterIds.length >= MAX_REFERENCE_SELECTION ? (
          <p className="text-[11px] text-muted">{t('referenceLimitReached')}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
        <Select
          label={t('resolution')}
          hint={resolutionHint}
          value={resolution}
          onChange={(event) =>
            setResolution(event.target.value as '480p' | '720p' | '1080p' | '2K')
          }
          options={[
            { value: '2K', label: t('resolution2k') },
            { value: '1080p', label: t('resolutionFhd') },
            { value: '720p', label: t('resolutionHd') },
            { value: '480p', label: t('resolutionSd') },
          ]}
        />
        <OptionGroup
          label={t('orientation')}
          value={orientation}
          onChange={(value) =>
            setAspect(
              value === 'landscape'
                ? LANDSCAPE_ASPECTS[0]
                : value === 'portrait'
                  ? PORTRAIT_ASPECTS[0]
                  : ADAPTIVE_ASPECT,
            )
          }
          columns={3}
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
            {
              value: 'adaptive' as const,
              label: t('orientationAdaptive'),
              icon: <IconGear className="size-4" />,
            },
          ]}
        />
        {aspectOptions.length > 0 ? (
          <OptionGroup
            label={t('aspect')}
            value={aspect}
            onChange={setAspect}
            options={aspectOptions.map((value) => ({ value, label: value }))}
          />
        ) : null}
        <OptionGroup
          label={t('duration')}
          value={duration}
          onChange={setDuration}
          options={DURATIONS.map((value) => ({
            value,
            label: t('durationSeconds', { count: value }),
          }))}
        />
      </div>

      <CollapsibleSection
        label={t('moreSettings')}
        icon={<IconGear className="size-4 text-muted" />}
      >
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
        <Select
          label={t('modelSelectLabel')}
          hint={t('modelSelectHint')}
          value={forcedModel}
          onChange={(event) => setForcedModel(event.target.value)}
          options={[
            { value: '', label: t('modelAuto') },
            ...modelOptions.map((option) => ({ value: option.model, label: option.label })),
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection
        label={t('referenceFramesGroup')}
        defaultOpen={referenceMode === 'frame_images'}
      >
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
      </CollapsibleSection>

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

  const polishSegment: PromptEnhanceScriptSegment | undefined = located
    ? { heading: located.scene.heading, blocks: shootablePolishBlocks(shown.blocks) }
    : undefined;

  const promptComposer = (
    <PromptComposer
      prompt={prompt}
      onChange={setPrompt}
      polishContext={{
        operation,
        aspectRatio: aspect,
        durationSeconds: duration,
        qualityTier: tier,
        styleHint,
        hasReference: uploads.length > 0,
        scriptSegment: polishSegment,
      }}
      onPolishAccept={handlePolishAccept}
      onPolishPendingChange={setPolishPending}
      skillMention={{
        skills: mentionableSkills,
        selectedIds: appliedSkillIds,
        maxReached: appliedSkillIds.length >= MAX_APPLIED_SKILLS,
        onSelect: applySkill,
      }}
      skillChips={appliedSkillChips}
      unlockDialog={unlockDialog}
      tip={{ title: t('directHint'), body: t('directHintBody') }}
      after={
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted">{tScript('clipSegmentLabel')}</p>
          {shown.environment.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <p className="text-[11px] text-muted">{tScript('clipEnvironmentLabel')}</p>
              {shown.environment.map((block, index) => (
                <ScriptBlockRow key={`env-${index}`} block={block} />
              ))}
            </div>
          ) : null}
          {shown.blocks.map((block, index) => (
            <ScriptBlockRow key={`${block.type}-${index}`} block={block} />
          ))}
        </div>
      }
    />
  );

  const previewSlot = displayJob ? (
    <>
      <InlineVideoResult
        job={displayJob}
        events={jobEvents}
        connected={jobConnected}
        reconnecting={jobReconnecting}
        liveThinking={liveThinking.text}
        draftId={draftId}
        linkedEpisodeId={linkedEpisodeId || null}
        onLinkedEpisode={setLinkedEpisodeId}
        cancelling={cancelling}
        onCancel={() => void cancelActiveJob()}
        onUseAsReference={(job) => void handleUseAsReference(job)}
        onRetried={(job) => {
          setActiveJobId(job.id);
          setActiveJobSeed(job);
        }}
        onPromoted={(job) => {
          setActiveJobId(job.id);
          setActiveJobSeed(job);
        }}
      />
      <GenerationVersionHistory
        jobs={knownJobs}
        activeJob={displayJob}
        appliedJobId={appliedJobId}
        draftId={draftId}
        onSelect={selectVersion}
        onAppliedChange={handleAppliedChange}
        onHidden={handleHiddenVersion}
      />
    </>
  ) : undefined;

  return (
    <GenerationStudioShell
      uploads={uploads}
      onUploaded={(asset) => setUploads((current) => [...current, asset])}
      onRemove={removeUpload}
      isPortraitPreview={orientation === 'portrait'}
      previewSlot={previewSlot}
      promptSlot={promptComposer}
      canSubmit={canSubmit}
      submitting={Boolean(busy)}
      submitLabel={t(studioSubmitLabelKey(busy))}
      onSubmit={runSubmit}
      price={price}
      estimate={estimate}
      error={error}
    >
      {paramsPanel}
    </GenerationStudioShell>
  );
}
