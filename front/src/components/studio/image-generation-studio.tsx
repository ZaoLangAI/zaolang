'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { GenerationVersionHistory } from '@/components/studio/generation-version-history';
import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { InlineImageResult } from '@/components/studio/inline-image-result';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptComposer } from '@/components/studio/prompt-composer';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { MAX_APPLIED_SKILLS, useAppliedSkills } from '@/components/studio/use-applied-skills';
import { Select } from '@/components/ui/field';
import { IconLandscape, IconPortrait } from '@/components/ui/icons';
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
import {
  CHARACTER_COMPLETION_PROMPT,
  canCompleteViews,
  findCompletionJobFor,
  missingReferenceViews,
} from '@/lib/characters';
import { formatCount, formatDuration } from '@/lib/format';
import { draftReturnParams } from '@/lib/studio-session';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useJobStream } from '@/lib/use-job-stream';
import { useResource } from '@/lib/use-resource';

type Operation = 'text_to_image' | 'image_to_image';
/** What a `text_to_image`/`image_to_image` output is *for* — mirrors the
 * backend's `ImageAssetKind` (`back/app/models/enums.py`). Picking `character`
 * here always generates just the front view (`GenerationParams.character_views`
 * defaults to `['front']`); the remaining two views are a separate,
 * standalone completion action on the character library card, not a studio
 * option (see `CharacterLibrary`'s "补全侧面/背面" button). */
const ASSET_KINDS = ['general', 'character', 'scene', 'cover'] as const;
type AssetKind = (typeof ASSET_KINDS)[number];
type Orientation = 'landscape' | 'portrait';

// No `1:1`: every framing the studio offers is either wider or taller than
// square, so orientation is always a meaningful first choice.
const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9'] as const;
const PORTRAIT_ASPECTS = ['9:16', '3:4'] as const;
const PORTRAIT_ASPECT = '9:16';

/**
 * "图片创作" — the merged `text_to_image`/`image_to_image` card from
 * `create-mode-cards.tsx`. Attaching an uploaded reference is what turns this
 * into an edit (same derivation shape `VideoGenerationStudio` uses for
 * `text_to_video → image_to_video`).
 *
 * Deliberately has no style preset / system style ("画风库") picker — those
 * live in `VideoGenerationStudio`/`AudioGenerationStudio` via
 * `useStyleAndSkillPicker`. Template skills are applied from the prompt
 * field's `@` menu (`useAppliedSkills`), not a second dropdown — video
 * uses the same `@` path (`showCreationSkillSelect: false`).
 *
 * Generation never navigates away to `/jobs/[jobId]`: a submit's progress and
 * result render inline in the preview slot (`InlineImageResult`), and every
 * job filed under the same draft shows up in `GenerationVersionHistory`
 * beneath it, so the user can jump back to any earlier iteration's image and
 * prompt and use it as the next one's reference (`handleUseAsReference`).
 */
export function ImageGenerationStudio({
  source,
  reference,
  initialPrompt,
  initialDraft,
  initialJobId,
  initialAssetKind,
  initialTargetCharacterId,
  initialTargetSceneId,
  subjectNameHint,
  returnTo,
  returnLinkKind,
  returnLinkLabel,
  linkEpisodeId,
}: {
  source?: StudioSource;
  reference?: WorkDetail;
  initialPrompt?: string;
  /** Resumes a previous session — `?draftId=` on `/create/new` — so its full
   * version history and latest output reappear instead of starting blank. */
  initialDraft?: Draft;
  /** Notification click-through (`?jobId=`). Preferred over
   * `initialDraft.latest_job_id` so a retry's queued/succeeded toast opens
   * that attempt, not the first failed one. */
  initialJobId?: string;
  /**
   * The next five props are the "文案创作 → 图片创作" deep link's payload
   * (assembled by `script-document-view.tsx`'s `buildCreateHref`, read back
   * on `/create/new`): pre-fill this session so a character chip/scene
   * heading jump-out lands straight on the right asset kind and target
   * instead of the user re-picking what they just clicked.
   */
  initialAssetKind?: AssetKind;
  initialTargetCharacterId?: string;
  initialTargetSceneId?: string;
  /** Names the new character/scene skill exactly when there is no target id
   * to auto-create one for — see `GenerationParams.subject_name_hint`. */
  subjectNameHint?: string;
  /** Where "返回文案创作" (`InlineImageResult`) navigates back to — only
   * ever a validated internal path (see `parseReturnTo` on `/create/new`),
   * never rendered directly from the raw query string. */
  returnTo?: string;
  returnLinkKind?: 'character' | 'scene';
  returnLinkLabel?: string;
  /** The short-drama workspace's "去图片创作" jump-out (`?linkEpisodeId=`) —
   * see `GenerationSubmitInput.linkEpisodeId`. */
  linkEpisodeId?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { status: sessionStatus } = useSession();
  const { notify } = useToast();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  // A resumed draft's `params.aspect_ratio` (written once at draft creation,
  // see `use-generation-submit.ts`) is already on hand synchronously via
  // `initialDraft` — no need to wait on a job fetch the way `assetKind`/
  // `uploads` below do.
  const [aspect, setAspect] = useState<string>(() => {
    const draftParams = initialDraft?.params as Record<string, unknown> | undefined;
    const ratio = typeof draftParams?.aspect_ratio === 'string' ? draftParams.aspect_ratio : null;
    return ratio && ([...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS] as string[]).includes(ratio)
      ? ratio
      : '16:9';
  });
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  // Which uploaded reference the user clicked in `SourceMaterialRail` — shown
  // enlarged in the preview area until a job exists (see `previewSlot`
  // below) or the user picks a different one. Derived from `uploads` by id
  // rather than storing the `Asset` itself, so removing/re-adding the same
  // upload can't leave a stale object around.
  const [selectedUploadId, setSelectedUploadId] = useState<string | null>(null);
  // A counter, not a boolean: `PromptPolish` only reacts to this *changing*,
  // so every "生成我的版本" click needs a new value even if the drawer was
  // already closed — see `PromptPolish`'s `closeSignal` prop.
  const [polishCloseSignal, setPolishCloseSignal] = useState(0);
  // "图片创作" — what this output is for, and which existing character/scene
  // (if any) it should read from and write back to. See section 6.3 of the
  // asset-kind plan.
  const [assetKind, setAssetKind] = useState<AssetKind>(initialAssetKind ?? 'general');
  const [targetCharacterId, setTargetCharacterId] = useState(initialTargetCharacterId ?? '');
  const [targetSceneId, setTargetSceneId] = useState(initialTargetSceneId ?? '');
  const [autoAttachToRoster, setAutoAttachToRoster] = useState(true);

  // Inline progress/result + version history state. `draftId` is created on
  // the first submit and reused by every later "continue refining" submit,
  // so the whole session's iterations file under one draft (see
  // `GenerationVersionHistory`). `activeJobId`/`activeJobSeed` name whichever
  // job the preview slot currently shows — either the one just submitted or
  // one picked from history — and are always set together so `useJobStream`
  // never mixes state from two different jobs.
  const [draftId, setDraftId] = useState<string | null>(initialDraft?.id ?? null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobSeed, setActiveJobSeed] = useState<GenerationJob | null>(null);
  const [cancelling, setCancelling] = useState(false);

  // Notification `?jobId=` wins over the draft's `latest_job_id` so a
  // retry toast opens that job. A 404 on the preferred id (deleted / not
  // owned) falls back to `latest_job_id` rather than leaving the preview
  // empty. Fetch once so the preview slot can seed `useJobStream` without
  // an initial null-`initial` SSE round-trip against an almost certainly
  // already-terminal job.
  const [resumeFallbackJobId, setResumeFallbackJobId] = useState<string | null>(null);
  const preferredResumeJobId =
    resumeFallbackJobId ?? initialJobId ?? initialDraft?.latest_job_id ?? null;
  const resumedJob = useResource<GenerationJob>(
    !activeJobId && preferredResumeJobId ? `/v1/generation-jobs/${preferredResumeJobId}` : null,
  );
  if (
    !activeJobId &&
    !resumeFallbackJobId &&
    initialJobId &&
    initialDraft?.latest_job_id &&
    initialJobId !== initialDraft.latest_job_id &&
    resumedJob.status === 'failed'
  ) {
    setResumeFallbackJobId(initialDraft.latest_job_id);
  }
  // Adjusted during render rather than in an effect (same pattern as
  // `command-palette.tsx`) — guarded by `!activeJobId` so it only ever fires
  // once, the moment the resumed job's data arrives. `asset_kind` rides
  // along here too — unlike `aspect` above it isn't on `Draft.params`, only
  // on the job response, so it can't be seeded from `initialDraft` alone.
  if (!activeJobId && resumedJob.status === 'ready' && resumedJob.data) {
    setActiveJobId(resumedJob.data.id);
    setActiveJobSeed(resumedJob.data);
    if (resumedJob.data.asset_kind && ASSET_KINDS.includes(resumedJob.data.asset_kind)) {
      setAssetKind(resumedJob.data.asset_kind);
    }
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
  // `useJobStream`'s own reset effect catching up (see `use-job-stream.ts`) —
  // without this, switching jobs could flash the previous job's data.
  const displayJob = liveJob && liveJob.id === activeJobId ? liveJob : activeJobSeed;

  // Every job seen under this draft so far — seeded once from the draft's
  // job list, then additively kept up to date below as jobs are submitted,
  // streamed, or picked from history. Fed to `GenerationVersionHistory`
  // (instead of just `activeJob`) so a version never disappears just
  // because it stopped being the one currently shown — the bug this state
  // exists to fix.
  const [knownJobsById, setKnownJobsById] = useState<Record<string, GenerationJob>>({});
  const knownJobs = useMemo(() => Object.values(knownJobsById), [knownJobsById]);

  const draftJobsHistory = useResource<Page<GenerationJob>>(
    draftId ? `/v1/generation-jobs?draft_id=${draftId}` : null,
  );
  // Guarded by a ref (same shape as `use-job-stream.ts`'s own reset effect)
  // rather than just the dependency, so it only ever seeds once, the
  // moment the one-shot fetch's data arrives. It only ever *fills in* jobs
  // this session hasn't observed directly yet, never overwrites a job's
  // already-known (necessarily fresher) local state.
  const historySeededRef = useRef(false);
  useEffect(() => {
    if (historySeededRef.current || !draftJobsHistory.data) return;
    historySeededRef.current = true;
    const seeded: Record<string, GenerationJob> = {};
    for (const job of draftJobsHistory.data.items) seeded[job.id] = job;
    setKnownJobsById((current) => ({ ...seeded, ...current }));
  }, [draftJobsHistory.data]);
  // Remembers `displayJob`'s latest state every time its identity changes
  // (a new submit, a stream update, or picking a different version) — the
  // ref guard is what a bare `[displayJob]` dependency already gives an
  // effect for free, kept explicit so a second render triggered by anything
  // else in this component never replays the same remember.
  const lastRememberedDisplayJobRef = useRef<GenerationJob | null>(null);
  useEffect(() => {
    if (!displayJob || displayJob === lastRememberedDisplayJobRef.current) return;
    lastRememberedDisplayJobRef.current = displayJob;
    setKnownJobsById((current) => ({ ...current, [displayJob.id]: displayJob }));
  }, [displayJob]);

  // Only a single-view character job (the front view, `character_views`
  // unset or `['front']`) can still be missing side/back — a multi-view
  // completion job already produced everything one job can, so this (and
  // therefore the "补全侧面/背面" button below) goes back to `null` the
  // moment such a job becomes `displayJob`, with no extra state to reset.
  const completionCharacterId =
    displayJob?.asset_kind === 'character' &&
    displayJob.status === 'succeeded' &&
    (!displayJob.character_views || displayJob.character_views.length <= 1)
      ? displayJob.linked_character_id ?? (targetCharacterId || null)
      : null;

  // Which already-submitted completion job (in flight or long since
  // succeeded, this session or a prior one) supplements `displayJob`,
  // derived purely from `knownJobs` — see `findCompletionJobFor`. This is
  // the primary signal for both the gallery merge (`InlineImageResult`)
  // and the button's availability below, so it works correctly even before
  // (or without ever needing) the character-record fetch beneath it.
  const resolvedCompletionJob = displayJob ? findCompletionJobFor(knownJobs, displayJob) : null;

  // The "补全侧面/背面" completion job gets its own submit/streaming state
  // rather than reusing the main `submit()`/`activeJobId` — otherwise its
  // `onSubmitted` would swap `activeJobId` to the completion job itself,
  // making it look like a second version of the *same* draft (the original
  // bug). The selected version stays whichever front-view job it already
  // was; the completion job's outputs are merged into that version's own
  // gallery instead (see `InlineImageResult`).
  const [completionJobId, setCompletionJobId] = useState<string | null>(null);
  const [completionJobSeed, setCompletionJobSeed] = useState<GenerationJob | null>(null);
  const { job: completionLiveJob } = useJobStream(completionJobId ?? '', completionJobSeed);
  const completionDisplayJob =
    completionLiveJob && completionLiveJob.id === completionJobId
      ? completionLiveJob
      : completionJobSeed;
  const lastRememberedCompletionJobRef = useRef<GenerationJob | null>(null);
  useEffect(() => {
    if (!completionDisplayJob || completionDisplayJob === lastRememberedCompletionJobRef.current) {
      return;
    }
    lastRememberedCompletionJobRef.current = completionDisplayJob;
    setKnownJobsById((current) => ({
      ...current,
      [completionDisplayJob.id]: completionDisplayJob,
    }));
  }, [completionDisplayJob]);

  // Fetched by id rather than trusted from `charactersResource`'s list
  // snapshot below — a character this very job just auto-created might not
  // be in that list yet. Kept as a plain fetch (not `useResource`) so it can
  // be forced to refetch via `characterRefreshNonce` once a completion
  // succeeds — a fallback safety net for "this character was already
  // completed elsewhere, outside any job this draft knows about".
  const [completionCharacterData, setCompletionCharacterData] = useState<Character | null>(null);
  const [characterRefreshNonce, setCharacterRefreshNonce] = useState(0);
  // Bumps the nonce the moment `completionDisplayJob` first reports
  // `succeeded` — the ref guard (same shape as the effects above) makes
  // sure this only fires on that one transition, not every render.
  const lastCompletionStatusRef = useRef<string | null>(null);
  useEffect(() => {
    const status = completionDisplayJob?.status ?? null;
    const justSucceeded = status === 'succeeded' && lastCompletionStatusRef.current !== 'succeeded';
    lastCompletionStatusRef.current = status;
    if (!justSucceeded) return;
    setCharacterRefreshNonce((n) => n + 1);
  }, [completionDisplayJob?.status]);
  useEffect(() => {
    if (!completionCharacterId) return;
    let cancelled = false;
    void api
      .get<Character>(`/v1/characters/${completionCharacterId}`)
      .then((data) => {
        if (!cancelled) setCompletionCharacterData(data);
      })
      .catch(() => {
        if (!cancelled) setCompletionCharacterData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [completionCharacterId, characterRefreshNonce]);
  // `completionCharacterData` only ever reflects whichever character the
  // effect above most recently fetched (or is about to) — once
  // `completionCharacterId` itself goes back to `null`, stop trusting
  // whatever that last fetch left behind rather than clearing it with a
  // second render.
  const effectiveCompletionCharacterData = completionCharacterId ? completionCharacterData : null;
  const canOfferCompleteViews = Boolean(
    completionCharacterId &&
      !resolvedCompletionJob &&
      effectiveCompletionCharacterData &&
      canCompleteViews(effectiveCompletionCharacterData),
  );
  // Priced (and later submitted) as whichever of side/back is still missing —
  // shared between the quote below and `completeCharacterViews`'s own submit
  // so the estimate the user sees before clicking always matches what gets
  // reserved. Falls back to both when there's nothing to derive it from yet
  // (button is hidden in that case anyway via `canOfferCompleteViews`).
  const missingCompletionViews: Array<'side' | 'back'> = effectiveCompletionCharacterData
    ? missingReferenceViews(effectiveCompletionCharacterData)
    : ['side', 'back'];

  const {
    quote: completionQuote,
    submitting: completionSubmitting,
    submit: submitCompletion,
  } = useGenerationSubmit(
    {
      operation: 'image_to_image',
      qualityTier: tier,
      durationSeconds: 0,
      assetKind: 'character',
      characterViews: missingCompletionViews,
    },
    {
      label: t('submit'),
      onSubmitted: (job) => {
        setCompletionJobId(job.id);
        setCompletionJobSeed(job);
      },
    },
  );
  const completingCharacterViews =
    completionSubmitting ||
    (completionDisplayJob != null &&
      !['succeeded', 'failed', 'cancelled', 'expired'].includes(completionDisplayJob.status));

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
  };

  const handleUseAsReference = useCallback(
    async (job: GenerationJob) => {
      const assetIds = job.output_asset_ids?.length
        ? job.output_asset_ids
        : job.output_asset_id
          ? [job.output_asset_id]
          : [];
      if (assetIds.length === 0) return;
      try {
        const assets = await Promise.all(assetIds.map((id) => api.get<Asset>(`/v1/assets/${id}`)));
        // Replaces rather than appends: "基于这张图" means this becomes the new
        // base image, not one more reference alongside whatever was there.
        setUploads(assets);
      } catch (caught) {
        notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
        return;
      }
      if (job.prompt) setPrompt(job.prompt);
    },
    [notify, tStates],
  );

  // `/remix/[workId]` hands this studio a licensed image source expecting
  // `image_to_image` to actually edit *that* image — unlike a video source
  // (auto-prepended server-side by `attach_licensed_source_video`), an image
  // reference is the caller's job to attach (see that function's own doc
  // comment), so without this the remix would silently submit as a bare
  // `image_to_image` with no reference at all. Runs once per mount, guarded
  // the same way the draft-resume effect below is.
  const sourceMaterialSeededRef = useRef(false);
  useEffect(() => {
    if (sourceMaterialSeededRef.current || !source) return;
    const assetId = source.work.current_version?.output_asset_id;
    if (!assetId) return;
    sourceMaterialSeededRef.current = true;
    void api
      .get<Asset>(`/v1/assets/${assetId}`)
      .then((asset) => setUploads([asset]))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Resuming a draft (`?draftId=` — the "最近草稿"/"草稿" tab's edit entry
  // points, and image job notifications) means the user wants to keep
  // working on it: pull its latest output into `uploads` and its prompt back
  // into the field, exactly like clicking "基于此图继续微调" on it would —
  // once, the moment the resumed job's data is in. Guarded by a ref (not
  // `resumedJob.data` itself) so a later version pick from
  // `GenerationVersionHistory` never re-triggers this.
  //
  // Doesn't just delegate to `handleUseAsReference`: that helper bails out
  // entirely when the job has no output (nothing to base an edit on), which
  // is right for its own "基于此图继续微调" button but wrong here — a failed
  // or still-running draft has no output yet either, and the prompt the
  // user originally typed is still worth restoring for a retry.
  // Keyed off `activeJobSeed` rather than `resumedJob.data` — the moment the
  // render-time block above sets `activeJobId`, `resumedJob`'s own query
  // switches to `null` (its `!activeJobId` guard) and its `data` reverts to
  // `undefined`, but `activeJobSeed` was already copied from it and stays
  // put, so it's the reliable read once a resumed job exists.
  const draftMaterialSeededRef = useRef(false);
  useEffect(() => {
    if (draftMaterialSeededRef.current || !initialDraft || !activeJobSeed) return;
    draftMaterialSeededRef.current = true;
    const job = activeJobSeed;
    void (async () => {
      if (job.prompt) setPrompt(job.prompt);
      await handleUseAsReference(job);
    })();
  }, [initialDraft, activeJobSeed, handleUseAsReference]);

  const charactersResource = useResource<Character[]>(
    sessionStatus === 'authenticated' ? '/v1/characters' : null,
  );
  const scenesResource = useResource<Scene[]>(
    sessionStatus === 'authenticated' ? '/v1/scenes' : null,
  );
  const characters = charactersResource.data ?? [];
  const scenes = scenesResource.data ?? [];
  const isCharacterAssetKind = assetKind === 'character';

  const hasImageReference = uploads.some((asset) => asset.media_type === 'image');
  const operation: Operation = source || hasImageReference ? 'image_to_image' : 'text_to_image';
  const isImageEdit = operation === 'image_to_image';

  const applyParams = (params: Record<string, unknown>) => {
    const aspectRatio = params.aspect_ratio;
    if (
      typeof aspectRatio === 'string' &&
      ([...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS] as string[]).includes(aspectRatio)
    ) {
      setAspect(aspectRatio);
    }
    const promptSuffix = params.prompt_suffix;
    if (typeof params.prompt === 'string' && params.prompt.trim()) {
      setPrompt(params.prompt);
    } else if (typeof promptSuffix === 'string' && promptSuffix.trim()) {
      setPrompt((current) => (current.trim() ? `${current}, ${promptSuffix}` : promptSuffix));
    }
  };

  const {
    mentionableSkills,
    appliedSkillIds,
    applySkill,
    chips: appliedSkillChips,
    unlockDialog,
  } = useAppliedSkills({ operation, onApplyParams: applyParams });

  // Derived, not its own state: an independent `orientation` could disagree
  // with `aspect` the moment a preset/skill/style applies one directly, and
  // then the "adjust while rendering" fix for that disagreement would have to
  // run every render. Deriving it removes the disagreement instead.
  const orientation: Orientation = (LANDSCAPE_ASPECTS as readonly string[]).includes(aspect)
    ? 'landscape'
    : 'portrait';
  const aspectOptions = orientation === 'landscape' ? LANDSCAPE_ASPECTS : PORTRAIT_ASPECTS;

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation, qualityTier: tier, durationSeconds: 0 },
    {
      label: t('submit'),
      // Stays on the studio page instead of navigating to `/jobs/[jobId]` —
      // the preview slot below picks up the new job and streams its own
      // progress. `job.draft_id` is always set here (the API only omits it
      // when the caller never sent one), so every later "continue refining"
      // submit reuses the same draft automatically.
      onSubmitted: (job) => {
        setDraftId(job.draft_id ?? draftId);
        setActiveJobId(job.id);
        setActiveJobSeed(job);
      },
    },
  );

  const canSubmit =
    prompt.trim().length > 0 && rightsConfirmed && !submitting && (quote?.sufficient ?? true);

  const removeUpload = (assetId: string) => {
    setUploads((current) => current.filter((asset) => asset.id !== assetId));
    setSelectedUploadId((current) => (current === assetId ? null : current));
  };

  const runSubmit = () => {
    setPolishCloseSignal((n) => n + 1);
    return submit({
      operation,
      qualityTier: tier,
      durationSeconds: 0,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      referenceAssetIds: uploads.map((asset) => asset.id),
      extra: {},
      skillIds: appliedSkillIds,
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
      draftId: draftId ?? undefined,
      assetKind,
      targetCharacterId: isCharacterAssetKind ? targetCharacterId || null : undefined,
      targetSceneId: assetKind === 'scene' ? targetSceneId || null : undefined,
      autoAttachAsset: isCharacterAssetKind ? autoAttachToRoster : undefined,
      subjectNameHint: isCharacterAssetKind || assetKind === 'scene' ? subjectNameHint : undefined,
      linkEpisodeId,
      draftParams: draftReturnParams({
        returnTo,
        returnLinkKind,
        returnLinkLabel,
      }),
    });
  };

  // Mirrors `CharacterLibrary`'s own "补全侧面/背面" request (same fixed
  // `3:4` aspect, same fixed reference-only prompt) but through this
  // studio's own, independent completion submit/stream state
  // (`submitCompletion`) rather than the main `submit()` — see the state
  // above. The reference image attached (the front view) keeps side/back
  // visually consistent; the backend (`execute_asset_planning`) hard-
  // overrides whatever prompt is sent here for a side/back pass anyway, but
  // sending the same fixed instruction keeps this request's own intent
  // self-explanatory instead of silently relying on that override.
  //
  // Requests only whichever of side/back `completionCharacterData` still
  // lacks (`missingReferenceViews`) rather than always both — otherwise
  // clicking this after already regenerating just one of them (e.g. right
  // after deleting it in the character library) would silently overwrite
  // the other, already-approved view too.
  const completeCharacterViews = () => {
    if (!displayJob?.output_asset_id || !completionCharacterId) return;
    if (missingCompletionViews.length === 0) return;
    submitCompletion({
      operation: 'image_to_image',
      qualityTier: tier,
      durationSeconds: 0,
      prompt: CHARACTER_COMPLETION_PROMPT,
      aspectRatio: '3:4',
      referenceAssetIds: [displayJob.output_asset_id],
      assetKind: 'character',
      characterViews: missingCompletionViews,
      targetCharacterId: completionCharacterId,
      autoAttachAsset: true,
      draftId: draftId ?? undefined,
    });
  };

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const paramsPanel = (
    <>
      <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
        <OptionGroup
          label={t('assetKind')}
          value={assetKind}
          onChange={(value) => {
            setAssetKind(value);
            if (value !== 'character') setTargetCharacterId('');
            if (value !== 'scene') setTargetSceneId('');
          }}
          columns={3}
          options={[
            { value: 'general' as const, label: t('assetKindGeneral') },
            { value: 'character' as const, label: t('assetKindCharacter') },
            { value: 'scene' as const, label: t('assetKindScene') },
            { value: 'cover' as const, label: t('assetKindCover') },
          ]}
        />
        <p className="text-[11px] text-muted">
          {assetKind === 'character' ? t('assetKindCharacterHint') : t('assetKindHint')}
        </p>

        {isCharacterAssetKind ? (
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

        {assetKind === 'scene' ? (
          <div className="flex flex-col gap-2">
            <Select
              label={t('targetScene')}
              value={targetSceneId}
              onChange={(event) => setTargetSceneId(event.target.value)}
              options={[
                { value: '', label: t('targetSceneNone') },
                ...scenes.map((scene) => ({ value: scene.id, label: scene.name })),
              ]}
            />
            <Link href="/create/scenes" className="text-[11px] text-muted hover:text-text">
              {t('manageScenesLink')}
            </Link>
          </div>
        ) : null}
      </div>

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

  // Only consulted by the shell while there's no `previewSlot` yet (before
  // the first submit) — once a job exists, the result takes over the
  // preview area regardless of what was last clicked in the source rail.
  const selectedUpload = uploads.find((asset) => asset.id === selectedUploadId) ?? null;

  // Renders below the preview area (`GenerationStudioShell`'s `promptSlot`)
  // rather than inside `paramsPanel` — see `PromptComposer`'s own doc
  // comment. No `tip` here: the "写得更像导演" copy never applied well to a
  // still image, same reasoning the old `hideDirectHint` flag captured.
  const promptComposer = (
    <PromptComposer
      prompt={prompt}
      onChange={setPrompt}
      polishContext={{
        operation,
        aspectRatio: aspect,
        qualityTier: tier,
        hasReference: uploads.length > 0 || Boolean(source),
        assetKind,
      }}
      onPolishAccept={setPrompt}
      closePolishSignal={polishCloseSignal}
      skillMention={{
        skills: mentionableSkills,
        selectedIds: appliedSkillIds,
        maxReached: appliedSkillIds.length >= MAX_APPLIED_SKILLS,
        onSelect: applySkill,
      }}
      skillChips={appliedSkillChips}
      unlockDialog={unlockDialog}
      hint={isImageEdit ? t('referenceRequiredHint') : undefined}
    />
  );

  // Undefined before the first submit (and while a resumed draft's job is
  // still loading), so the shell falls back to its default cover/poster —
  // once set, it fully replaces that block with the live/finished result
  // plus the version-history strip right beneath it.
  const previewSlot = displayJob ? (
    <>
      <InlineImageResult
        job={displayJob}
        events={jobEvents}
        connected={jobConnected}
        reconnecting={jobReconnecting}
        liveThinking={liveThinking.text}
        draftId={draftId}
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
        returnTo={returnTo}
        returnLinkKind={returnLinkKind}
        returnLinkLabel={returnLinkLabel}
        fallbackLinkRefId={targetCharacterId || targetSceneId || undefined}
        completionJob={resolvedCompletionJob}
        canCompleteCharacterViews={canOfferCompleteViews}
        completingCharacterViews={completingCharacterViews}
        onCompleteCharacterViews={completeCharacterViews}
        completionCredits={completionQuote?.credits}
      />
      <GenerationVersionHistory jobs={knownJobs} activeJob={displayJob} onSelect={selectVersion} />
    </>
  ) : undefined;

  return (
    <GenerationStudioShell
      source={source}
      reference={reference}
      uploads={uploads}
      onUploaded={(asset) => setUploads((current) => [...current, asset])}
      onRemove={removeUpload}
      onSelectUpload={(asset) => setSelectedUploadId(asset.id)}
      isPortraitPreview={aspect === PORTRAIT_ASPECT}
      previewSlot={previewSlot}
      promptSlot={promptComposer}
      previewOverrideUrl={selectedUpload?.url ?? null}
      previewPlaceholder={t('previewAreaLabel')}
      hideDirectHint
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