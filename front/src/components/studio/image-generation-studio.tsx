'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { GenerationVersionHistory } from '@/components/studio/generation-version-history';
import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { InlineImageResult } from '@/components/studio/inline-image-result';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptField } from '@/components/studio/prompt-field';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { Select } from '@/components/ui/field';
import { IconLandscape, IconPortrait } from '@/components/ui/icons';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { Character, Draft, GenerationJob, QualityTier, Scene, WorkDetail } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
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
type AssetKind = 'general' | 'character' | 'scene' | 'cover';
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
 * Deliberately has no style preset / creation skill / system style picker —
 * those live only in `VideoGenerationStudio`/`AudioGenerationStudio` via
 * `useStyleAndSkillPicker`. This shell never fetches `/v1/style-presets`,
 * `/v1/skills*` or `/v1/style-gallery/*` at all.
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
}: {
  source?: StudioSource;
  reference?: WorkDetail;
  initialPrompt?: string;
  /** Resumes a previous session — `?draftId=` on `/create/new` — so its full
   * version history and latest output reappear instead of starting blank. */
  initialDraft?: Draft;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { status: sessionStatus } = useSession();
  const { notify } = useToast();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [aspect, setAspect] = useState<string>('16:9');
  const [tier, setTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  // "图片创作" — what this output is for, and which existing character/scene
  // (if any) it should read from and write back to. See section 6.3 of the
  // asset-kind plan.
  const [assetKind, setAssetKind] = useState<AssetKind>('general');
  const [targetCharacterId, setTargetCharacterId] = useState('');
  const [targetSceneId, setTargetSceneId] = useState('');
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

  // Resuming `?draftId=` only gives us the draft, whose `latest_job_id` is a
  // bare id — fetch it once so the preview slot can seed `useJobStream`
  // without an initial null-`initial` SSE round-trip against an almost
  // certainly already-terminal job.
  const resumedJob = useResource<GenerationJob>(
    !activeJobId && initialDraft?.latest_job_id
      ? `/v1/generation-jobs/${initialDraft.latest_job_id}`
      : null,
  );
  // Adjusted during render rather than in an effect (same pattern as
  // `command-palette.tsx`) — guarded by `!activeJobId` so it only ever fires
  // once, the moment the resumed job's data arrives.
  if (!activeJobId && resumedJob.status === 'ready' && resumedJob.data) {
    setActiveJobId(resumedJob.data.id);
    setActiveJobSeed(resumedJob.data);
  }

  const {
    job: liveJob,
    events: jobEvents,
    connected: jobConnected,
    reconnecting: jobReconnecting,
    applyJob,
  } = useJobStream(activeJobId ?? '', activeJobSeed);
  // Guards against the one-render gap between setting `activeJobId` and
  // `useJobStream`'s own reset effect catching up (see `use-job-stream.ts`) —
  // without this, switching jobs could flash the previous job's data.
  const displayJob = liveJob && liveJob.id === activeJobId ? liveJob : activeJobSeed;

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

  const handleUseAsReference = async (job: GenerationJob) => {
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
  };

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
  };

  const runSubmit = () =>
    submit({
      operation,
      qualityTier: tier,
      durationSeconds: 0,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      referenceAssetIds: uploads.map((asset) => asset.id),
      extra: {},
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
      draftId: draftId ?? undefined,
      assetKind,
      targetCharacterId: isCharacterAssetKind ? targetCharacterId || null : undefined,
      targetSceneId: assetKind === 'scene' ? targetSceneId || null : undefined,
      autoAttachAsset: isCharacterAssetKind ? autoAttachToRoster : undefined,
    });

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

      <PromptField
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
      />

      {isImageEdit ? <p className="text-xs text-muted">{t('referenceRequiredHint')}</p> : null}

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
        draftId={draftId}
        cancelling={cancelling}
        onCancel={() => void cancelActiveJob()}
        onUseAsReference={(job) => void handleUseAsReference(job)}
        onRetried={(job) => {
          setActiveJobId(job.id);
          setActiveJobSeed(job);
        }}
      />
      <GenerationVersionHistory
        draftId={draftId}
        activeJob={displayJob}
        onSelect={selectVersion}
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
      isPortraitPreview={aspect === PORTRAIT_ASPECT}
      previewSlot={previewSlot}
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