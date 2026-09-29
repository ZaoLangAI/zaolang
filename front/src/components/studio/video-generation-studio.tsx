'use client';

import { useLocale, useTranslations } from 'next-intl';
import Image from 'next/image';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { CollapsibleSection } from '@/components/studio/collapsible-section';
import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import {
  STUDIO_RESOLUTION_LABEL_KEYS,
  adaptStudioResolution,
} from '@/components/studio/generation-resolution';
import { GenerationVersionHistory } from '@/components/studio/generation-version-history';
import {
  durationFromVersion,
  promptFromVersion,
  videoAssetKindFromVersion,
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
  QualityTier,
  Scene,
  WorkDetail,
} from '@/lib/api/types';
import { referenceByView } from '@/lib/characters';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { useGenerationModels } from '@/lib/use-generation-models';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useJobStream } from '@/lib/use-job-stream';
import { useResource } from '@/lib/use-resource';

type Operation = 'text_to_video' | 'image_to_video' | 'video_to_video';
type ReferenceMode = 'input_references' | 'frame_images';
type Orientation = 'landscape' | 'portrait' | 'adaptive';
/** What a video job's output is *for* — mirrors the backend's `VideoAssetKind`
 * (`back/app/models/enums.py`), the video-side equivalent of
 * `ImageGenerationStudio`'s `AssetKind`. `character_action` auto-attaches
 * the succeeded output to a character's clip list
 * (`execute_asset_output_link`); `transition_video`/`cover_video` are
 * tagged but not attached to any library, same as image's `cover` today. */
type VideoAssetKind = 'general' | 'character_action' | 'transition_video' | 'cover_video';
const VIDEO_ASSET_KINDS = [
  'general',
  'character_action',
  'transition_video',
  'cover_video',
] as const;

// No `1:1`: every framing the studio offers is either wider or taller than
// square, so orientation is always a meaningful first choice. The legal set
// here is a subset of the backend's per-model `NativeVideoModelProfile` —
// widest is MiniMax H3's ten ratios; a narrower-profiled native model (e.g.
// `wan2.7-videoedit`) is simply hard-filtered out of routing if a value
// outside its own profile is submitted (see `zaolang-frontend-ui` invariant
// #10).
const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9', '3:2'] as const;
const PORTRAIT_ASPECTS = ['9:16', '3:4', '2:3', '9:21'] as const;
// A third orientation, not a member of either bucket above: the provider
// picks the framing itself, so it has no landscape/portrait aspect list of
// its own — see the `aspectOptions` derivation below.
const ADAPTIVE_ASPECT = 'adaptive';
const ASPECTS = [...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS, ADAPTIVE_ASPECT] as const;
const DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
// Mirrors the backend's `GenerationParams.character_ids`/`scene_ids` cap
// (`max_length=4`) — the picker refuses a 5th selection client-side instead
// of letting submit fail with a 422.
const MAX_REFERENCE_SELECTION = 4;

/**
 * `/create/new` (`text_to_video` / `image_to_video` modes) and
 * `/remix/[workId]` (`video_to_video` when the source work is a video,
 * otherwise `image_to_video` — remix has no image/audio path). Keeps the
 * style preset / system style ("画风库") half of `useStyleAndSkillPicker`;
 * template skills apply from the prompt `@` menu (`useAppliedSkills`),
 * same as `ImageGenerationStudio`. `AudioGenerationStudio` is the shell
 * that still shows the creation-skill Select.
 *
 * Generation never navigates away to `/jobs/[jobId]` any more: a submit's
 * progress and result render inline in the preview slot
 * (`InlineVideoResult`), and every job filed under the same `Draft` shows up
 * in `GenerationVersionHistory` beneath it — the same architecture
 * `ImageGenerationStudio` already uses, extended here now that video
 * creation has its own per-draft version history too (see
 * `use-generation-submit.ts`'s `draftId`, generic across every operation on
 * the backend already).
 */
export function VideoGenerationStudio({
  operation: initialOperation,
  source,
  reference,
  initialPrompt,
  initialDraft,
  initialJobId,
  initialStyleParams,
  initialStyleGalleryId,
  initialVideoAssetKind,
  initialTargetCharacterId,
  subjectNameHint,
  initialReferenceCharacterIds,
  initialReferenceSceneIds,
  linkEpisodeId,
  linkBreakpointKey,
  initialSkillId,
}: {
  operation: 'text_to_video' | 'image_to_video' | 'video_to_video';
  /** A licensed remix source. Submitted as `source_work_id`. */
  source?: StudioSource;
  /** A work the idea came from, carried over from the discover feed. */
  reference?: WorkDetail;
  initialPrompt?: string;
  /**
   * Resumes a previous video-creation session — `?draftId=` on
   * `/create/new`, or the "最近草稿"/"草稿" tab's edit entry — so its full
   * version history and latest output (`GenerationVersionHistory`) reappear
   * instead of starting blank. Every later submit in this session reuses
   * the same draft id, exactly like `ImageGenerationStudio`.
   */
  initialDraft?: Draft;
  /** Notification click-through (`?jobId=`). Preferred over
   * `initialDraft.latest_job_id` so a retry's queued/succeeded toast opens
   * that attempt, not the first failed one. */
  initialJobId?: string;
  /** A style gallery entry's `params`, applied once on mount (from `?styleId=`). */
  initialStyleParams?: Record<string, unknown>;
  /** The catalogue id behind `initialStyleParams`; submitted as `style_gallery_id`. */
  initialStyleGalleryId?: string;
  /**
   * Pre-fills the asset-kind picker below — the character library's
   * "生成动作视频" button deep-links here the same way the script studio's
   * image jump-out pre-fills `ImageGenerationStudio`'s `initialAssetKind`
   * (see `zaolang-frontend-ui` invariant #16).
   */
  initialVideoAssetKind?: VideoAssetKind;
  initialTargetCharacterId?: string;
  /** Names the new character/scene skill exactly when there is no target id
   * to auto-create one for — see `GenerationParams.subject_name_hint`. */
  subjectNameHint?: string;
  /**
   * Pre-selects the reference-character/reference-scene picker below — the
   * script studio's "建议切分" chip (`buildBreakpointVideoHref`) deep-links
   * here with the segment's already-linked characters/scenes. Distinct from
   * `initialTargetCharacterId` above: that names an output auto-attach
   * target, these name generation *input* references (`characterIds`/
   * `sceneIds` on `useGenerationSubmit`). Only seeds the
   * initial selection — the picker stays fully user-editable afterward.
   */
  initialReferenceCharacterIds?: string[];
  initialReferenceSceneIds?: string[];
  /** The short-drama workspace's "去视频创作" jump-out (`?linkEpisodeId=`) —
   * see `GenerationSubmitInput.linkEpisodeId`. */
  linkEpisodeId?: string;
  /** Which script breakpoint this submit belongs to — see
   * `GenerationSubmitInput.linkBreakpointKey`. */
  linkBreakpointKey?: string;
  /**
   * Accepted for stale `?continuityAssetId=` deep links. First/last frames
   * are no longer auto-applied — the author picks them manually in the
   * reference-mode panel if they want shot continuity.
   */
  continuitySourceAssetId?: string;
  /** Plaza / `@` deep-link `?skillId=` — apply the recipe once on mount. */
  initialSkillId?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { status: sessionStatus } = useSession();
  const { notify } = useToast();

  const draftPrompt = initialDraft?.params?.prompt;
  const [prompt, setPrompt] = useState(
    source?.params.prompt ??
      (typeof draftPrompt === 'string' && draftPrompt ? draftPrompt : undefined) ??
      initialPrompt ??
      '',
  );
  // `Draft.params.aspect_ratio`/`duration_seconds` are written once, at the
  // draft's first submit — a session-level setting, not necessarily what
  // the *latest* job under it actually used, same trade-off
  // `ImageGenerationStudio` already accepts for its own `aspect` seed.
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
  // "指定模型" — opts this job out of the LLM-driven routing pick, see
  // `GenerationSubmitInput.forcedModel`. Empty means "自动选择", today's
  // unchanged behaviour.
  const [forcedModel, setForcedModel] = useState('');
  const [referenceMode, setReferenceMode] = useState<ReferenceMode>('input_references');
  const [firstFrameAssetId, setFirstFrameAssetId] = useState('');
  const [lastFrameAssetId, setLastFrameAssetId] = useState('');
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});
  // "视频创作" — what this output is for, and which existing character/scene
  // (if any) it should write back to. Mirrors `ImageGenerationStudio`'s own
  // asset-kind state one-for-one.
  const [videoAssetKind, setVideoAssetKind] = useState<VideoAssetKind>(
    initialVideoAssetKind ?? 'general',
  );
  const [targetCharacterId, setTargetCharacterId] = useState(initialTargetCharacterId ?? '');
  const [autoAttachToRoster, setAutoAttachToRoster] = useState(true);
  const [selectedReferenceCharacterIds, setSelectedReferenceCharacterIds] = useState<string[]>(
    initialReferenceCharacterIds ?? [],
  );
  const [selectedReferenceSceneIds, setSelectedReferenceSceneIds] = useState<string[]>(
    initialReferenceSceneIds ?? [],
  );

  // Inline progress/result + version history state — the same shape
  // `ImageGenerationStudio` uses. `draftId` is created on the first submit
  // and reused by every later "continue refining" submit, so the whole
  // session's iterations file under one draft.
  const [draftId, setDraftId] = useState<string | null>(initialDraft?.id ?? null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobSeed, setActiveJobSeed] = useState<GenerationJob | null>(null);
  const [appliedJobId, setAppliedJobId] = useState<string | null>(
    initialDraft?.applied_job_id ?? null,
  );
  const draftLinkedEpisode =
    typeof initialDraft?.params?.link_episode_id === 'string'
      ? initialDraft.params.link_episode_id
      : '';
  const [linkedEpisodeId, setLinkedEpisodeId] = useState(linkEpisodeId ?? draftLinkedEpisode);
  const [cancelling, setCancelling] = useState(false);
  const [polishPending, setPolishPending] = useState(false);

  // Notification `?jobId=` wins over the draft's applied / latest pointers
  // so a retry toast opens that job. A 404 on the preferred id (deleted /
  // not owned) falls back to the applied version, then `latest_job_id`.
  const [resumeFallbackJobId, setResumeFallbackJobId] = useState<string | null>(null);
  const resumeDefaultJobId = initialDraft?.applied_job_id ?? initialDraft?.latest_job_id ?? null;
  const preferredResumeJobId = resumeFallbackJobId ?? initialJobId ?? resumeDefaultJobId;
  const resumedJob = useResource<GenerationJob>(
    !activeJobId && preferredResumeJobId ? `/v1/generation-jobs/${preferredResumeJobId}` : null,
  );
  if (
    !activeJobId &&
    !resumeFallbackJobId &&
    initialJobId &&
    resumeDefaultJobId &&
    initialJobId !== resumeDefaultJobId &&
    resumedJob.status === 'failed'
  ) {
    setResumeFallbackJobId(resumeDefaultJobId);
  }
  // Adjusted during render rather than in an effect (same pattern as
  // `ImageGenerationStudio`), guarded by `!activeJobId` so it only ever
  // fires once, the moment the resumed job's data arrives. `video_asset_kind`
  // rides along here (not on `Draft.params`, only on the job response), same
  // as image's `asset_kind`. `prompt` is re-seeded from the resumed *job*
  // (not `initialDraft.params.prompt`, frozen at the draft's first submit)
  // so a several-versions-deep resume shows the actual last-edited prompt —
  // deliberately does *not* also re-attach that job's own output as a
  // reference upload the way `ImageGenerationStudio` does for its
  // image-to-image chaining: silently turning a plain "tweak the prompt and
  // regenerate" resume into a `video_to_video` job would be a surprising
  // default. `InlineVideoResult`'s "基于此视频继续创作" does that instead,
  // deliberately, on click.
  if (!activeJobId && resumedJob.status === 'ready' && resumedJob.data) {
    setActiveJobId(resumedJob.data.id);
    setActiveJobSeed(resumedJob.data);
    if (
      resumedJob.data.video_asset_kind &&
      (VIDEO_ASSET_KINDS as readonly string[]).includes(resumedJob.data.video_asset_kind)
    ) {
      setVideoAssetKind(resumedJob.data.video_asset_kind as VideoAssetKind);
    }
    if (resumedJob.data.prompt) setPrompt(resumedJob.data.prompt);
  }

  const {
    job: liveJob,
    events: jobEvents,
    connected: jobConnected,
    reconnecting: jobReconnecting,
    liveThinking,
    applyJob,
  } = useJobStream(activeJobId ?? '', activeJobSeed);
  // Guards against the one-render gap between setting `activeJobId` and
  // `useJobStream`'s own reset effect catching up — without this, switching
  // jobs could flash the previous job's data.
  const displayJob = liveJob && liveJob.id === activeJobId ? liveJob : activeJobSeed;

  // Every job seen under this draft so far — seeded once from the draft's
  // job list, then additively kept up to date below as jobs are submitted,
  // streamed, or picked from history. Fed to `GenerationVersionHistory`
  // (instead of just `displayJob`) so a version never disappears just
  // because it stopped being the one currently shown.
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
  // Adjusted during render rather than in an effect (same pattern as the
  // resumed-job handling above). Keyed on the succeeded job's id so it fires
  // once per success and never snaps back over a version applied afterwards.
  const succeededJobId =
    liveJob?.status === 'succeeded' && liveJob.id === activeJobId ? liveJob.id : null;
  const [lastSucceededJobId, setLastSucceededJobId] = useState<string | null>(null);
  if (succeededJobId !== lastSucceededJobId) {
    setLastSucceededJobId(succeededJobId);
    if (succeededJobId) setAppliedJobId(succeededJobId);
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
    const prompt = promptFromVersion(job);
    if (prompt) setPrompt(prompt);
    const durationSeconds = durationFromVersion(job, DURATIONS);
    if (durationSeconds !== null) setDuration(durationSeconds);
    const kind = videoAssetKindFromVersion(job, VIDEO_ASSET_KINDS);
    if (kind) setVideoAssetKind(kind);
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

  /** "基于此视频继续创作" — attaches `job`'s own output video as the next
   * submit's reference material (deliberately explicit, see the resume
   * effect's own doc comment above for why this is never automatic). */
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
  const toggleReferenceScene = (id: string) =>
    setSelectedReferenceSceneIds((current) =>
      current.includes(id)
        ? current.filter((existing) => existing !== id)
        : current.length < MAX_REFERENCE_SELECTION
          ? [...current, id]
          : current,
    );

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

  const sourceIsVideo =
    (source?.work.media_type ?? source?.work.current_version?.media_type) === 'video';
  const sourceOutputAssetId = source?.work.current_version?.output_asset_id ?? null;
  const hasVideoReference =
    uploads.some((asset) => asset.media_type === 'video') || sourceIsVideo;
  const hasImageReference = uploads.some((asset) => asset.media_type === 'image');
  let operation: Operation = initialOperation;
  if (initialOperation === 'text_to_video') {
    if (referenceMode === 'frame_images' && firstFrameAssetId) operation = 'image_to_video';
    else if (hasVideoReference) operation = 'video_to_video';
    else if (source || hasImageReference) operation = 'image_to_video';
  } else if (sourceIsVideo && referenceMode !== 'frame_images') {
    operation = 'video_to_video';
  }

  const modelOptions = useGenerationModels(operation);
  const forcedOption = modelOptions.find((option) => option.model === forcedModel);
  const resolutionPreview = useMemo(() => {
    if (sourceIsVideo || !forcedModel || !forcedOption) return null;
    return adaptStudioResolution(resolution, forcedOption.resolutions);
  }, [forcedModel, forcedOption, resolution, sourceIsVideo]);
  const resolutionHint = sourceIsVideo
    ? t('resolutionHint')
    : resolutionPreview && resolutionPreview.kind !== 'exact'
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
  const isCharacterActionKind = videoAssetKind === 'character_action';

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
    initialStyleParams,
    initialStyleGalleryId,
    onApplyParams: applyParams,
    showCreationSkillSelect: false,
    seedSkillId: initialSkillId,
  });

  // Derived, not its own state: an independent `orientation` could disagree
  // with `aspect` the moment a preset/skill/style applies one directly, and
  // then the "adjust while rendering" fix for that disagreement would have to
  // run every render. Deriving it removes the disagreement instead.
  const orientation: Orientation =
    aspect === ADAPTIVE_ASPECT
      ? 'adaptive'
      : (LANDSCAPE_ASPECTS as readonly string[]).includes(aspect)
        ? 'landscape'
        : 'portrait';
  // `adaptive` has no aspect-specific sub-list of its own — the provider
  // picks the framing, so there is nothing further to choose below the
  // orientation picker once it is selected.
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
      // Stays on the studio page instead of navigating to `/jobs/[jobId]` —
      // the preview slot below picks up the new job and streams its own
      // progress, and every later submit under the same draft becomes a new
      // version in `GenerationVersionHistory`.
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
    if (busy) return;
    return submit({
      operation,
      qualityTier: tier,
      durationSeconds: duration,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      seed: parsedSeed,
      referenceAssetIds:
        referenceMode === 'frame_images'
          ? []
          : [
              ...(sourceIsVideo && sourceOutputAssetId ? [sourceOutputAssetId] : []),
              ...uploads.map((asset) => asset.id),
            ],
      videoOptions: {
        ...(sourceIsVideo ? {} : { resolution }),
        reference_mode: referenceMode,
        first_frame_asset_id: referenceMode === 'frame_images' ? firstFrameAssetId || null : null,
        last_frame_asset_id: referenceMode === 'frame_images' ? lastFrameAssetId || null : null,
      },
      extra: { sound, ...presetExtra },
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      characterIds: selectedReferenceCharacterIds,
      sceneIds: selectedReferenceSceneIds,
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
      draftId: draftId ?? undefined,
      videoAssetKind,
      targetCharacterId: isCharacterActionKind ? targetCharacterId || null : undefined,
      autoAttachAsset: isCharacterActionKind ? autoAttachToRoster : undefined,
      subjectNameHint: isCharacterActionKind ? subjectNameHint : undefined,
      linkEpisodeId,
      linkBreakpointKey,
      forcedModel: forcedModel || undefined,
    });
  };

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const paramsPanel = (
    <>
      {styleAndSkillPicker}

      <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
        <OptionGroup
          label={t('videoAssetKind')}
          value={videoAssetKind}
          onChange={(value) => {
            setVideoAssetKind(value);
            if (value !== 'character_action') setTargetCharacterId('');
          }}
          columns={3}
          options={[
            { value: 'general' as const, label: t('videoAssetKindGeneral') },
            { value: 'character_action' as const, label: t('videoAssetKindCharacterAction') },
            { value: 'transition_video' as const, label: t('videoAssetKindTransition') },
            { value: 'cover_video' as const, label: t('videoAssetKindCover') },
          ]}
        />
        <p className="text-[11px] text-muted">{t('videoAssetKindHint')}</p>

        {isCharacterActionKind ? (
          <div className="flex flex-col gap-2">
            <Select
              label={t('targetCharacter')}
              hint={t('targetCharacterHint')}
              value={targetCharacterId}
              onChange={(event) => setTargetCharacterId(event.target.value)}
              options={[
                { value: '', label: t('targetCharacterAutoCreate') },
                ...characters.map((character) => ({
                  value: character.id,
                  label: character.name,
                })),
              ]}
            />
            <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed text-muted">
              <input
                type="checkbox"
                checked={autoAttachToRoster}
                onChange={(event) => setAutoAttachToRoster(event.target.checked)}
                className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
              />
              {t('autoAttachToRoster')}
            </label>
            {!autoAttachToRoster ? (
              <p className="text-[11px] text-muted">{t('autoAttachToRosterOffHint')}</p>
            ) : null}
            <Link href="/create/characters" className="text-[11px] text-muted hover:text-text">
              {t('manageCharactersLink')}
            </Link>
          </div>
        ) : null}

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <p className="text-xs text-muted">{t('referenceCastLabel')}</p>
          <p className="text-[11px] text-muted">{t('referenceCastHint')}</p>
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
                          <Image src={thumbnailUrl} alt="" fill sizes="28px" className="object-cover" />
                        ) : null}
                      </span>
                      {character.name}
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-xs text-muted">{t('referenceCastEmpty')}</p>
          )}

          <p className="mt-1 text-xs text-muted">{t('referenceScenesLabel')}</p>
          {scenes.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {scenes.map((scene) => {
                const checked = selectedReferenceSceneIds.includes(scene.id);
                const disabled =
                  !checked && selectedReferenceSceneIds.length >= MAX_REFERENCE_SELECTION;
                const thumbnailUrl = scene.reference_assets?.[0]?.url;
                return (
                  <li key={scene.id}>
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
                        onChange={() => toggleReferenceScene(scene.id)}
                        className="size-4 shrink-0 accent-[var(--primary)]"
                      />
                      <span className="relative size-7 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                        {thumbnailUrl ? (
                          <Image src={thumbnailUrl} alt="" fill sizes="28px" className="object-cover" />
                        ) : null}
                      </span>
                      {scene.name}
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-xs text-muted">{t('referenceScenesEmpty')}</p>
          )}
          {selectedReferenceCharacterIds.length >= MAX_REFERENCE_SELECTION ||
          selectedReferenceSceneIds.length >= MAX_REFERENCE_SELECTION ? (
            <p className="text-[11px] text-muted">{t('referenceLimitReached')}</p>
          ) : null}
        </div>
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

      <CollapsibleSection label={t('moreSettings')} icon={<IconGear className="size-4 text-muted" />}>
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

  // Renders below the preview area (`GenerationStudioShell`'s `promptSlot`)
  // rather than inside `paramsPanel` — see `PromptComposer`'s own doc
  // comment. `tip` folds the "写得更像导演" copy that used to be the shell's
  // standalone `directHint` box into this card's own header, so there is
  // one box here instead of two stacked ones.
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
        hasReference: uploads.length > 0 || Boolean(source),
        videoAssetKind,
      }}
      onPolishAccept={setPrompt}
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
    />
  );

  // Undefined before the first submit (and while a resumed draft's job is
  // still loading), so the shell falls back to its default poster/device
  // preview — once set, it fully replaces that block with the live/finished
  // result plus the version-history strip right beneath it.
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
      source={source}
      reference={reference}
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
