'use client';

import { useLocale, useTranslations } from 'next-intl';
import Image from 'next/image';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { CollapsibleSection } from '@/components/studio/collapsible-section';
import {
  GenerationStudioShell,
  type StudioSource,
} from '@/components/studio/generation-studio-shell';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptField } from '@/components/studio/prompt-field';
import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import {
  KNOWN_PRESET_KEYS,
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
import type { Character, Draft, QualityTier, Scene, WorkDetail } from '@/lib/api/types';
import { referenceByView } from '@/lib/characters';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
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
 * style preset / creation skill / system style picker exactly as it was
 * before the split (`ImageGenerationStudio` is the one shell that dropped it).
 */
export function VideoGenerationStudio({
  operation: initialOperation,
  source,
  reference,
  initialPrompt,
  initialDraft,
  initialStyleParams,
  initialStyleGalleryId,
  initialVideoAssetKind,
  initialTargetCharacterId,
  subjectNameHint,
  initialReferenceCharacterIds,
  initialReferenceSceneIds,
  linkEpisodeId,
  linkBreakpointKey,
}: {
  operation: 'text_to_video' | 'image_to_video' | 'video_to_video';
  /** A licensed remix source. Submitted as `source_work_id`. */
  source?: StudioSource;
  /** A work the idea came from, carried over from the discover feed. */
  reference?: WorkDetail;
  initialPrompt?: string;
  /**
   * Resumes an earlier video draft as *material* for a new `video_to_video`
   * session — the "最近草稿" edit shortcut's target (see `zaolang-frontend-ui`
   * / `RecentDraftCard`). Unlike `ImageGenerationStudio`'s `initialDraft`,
   * this never reuses the same draft id on submit: there is no per-draft
   * version history on the video side, so continuing to build on an old clip
   * always starts a fresh draft with the earlier output attached as a
   * reference upload.
   */
  initialDraft?: Draft;
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
  const [resolution, setResolution] = useState<'2K' | '768P'>('2K');
  const [seed, setSeed] = useState('');
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

  // Seeds the resumed draft's own output as the `video_to_video` material —
  // once only, guarded the same way `ImageGenerationStudio`'s
  // `draftMaterialSeededRef` is, so a later upload/removal is never
  // clobbered by this effect firing again.
  const draftMaterialSeededRef = useRef(false);
  useEffect(() => {
    const assetId = initialDraft?.output_asset_id;
    if (draftMaterialSeededRef.current || !assetId) return;
    draftMaterialSeededRef.current = true;
    void (async () => {
      try {
        const asset = await api.get<Asset>(`/v1/assets/${assetId}`);
        setUploads((current) => [...current, asset]);
      } catch (caught) {
        notify(isApiError(caught) ? caught.message : tStates('errorHint'), 'error');
      }
    })();
  }, [initialDraft, notify, tStates]);

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
  } = useStyleAndSkillPicker({
    operation,
    initialStyleParams,
    initialStyleGalleryId,
    onApplyParams: applyParams,
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
    { label: t('submit') },
  );

  const frameSelectionValid = referenceMode !== 'frame_images' || Boolean(firstFrameAssetId);
  const canSubmit =
    prompt.trim().length > 0 &&
    rightsConfirmed &&
    frameSelectionValid &&
    seedValid &&
    !submitting &&
    (quote?.sufficient ?? true);

  const removeUpload = (assetId: string) => {
    setUploads((current) => current.filter((asset) => asset.id !== assetId));
    if (firstFrameAssetId === assetId) setFirstFrameAssetId('');
    if (lastFrameAssetId === assetId) setLastFrameAssetId('');
  };

  const runSubmit = () =>
    submit({
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
      videoAssetKind,
      targetCharacterId: isCharacterActionKind ? targetCharacterId || null : undefined,
      autoAttachAsset: isCharacterActionKind ? autoAttachToRoster : undefined,
      subjectNameHint: isCharacterActionKind ? subjectNameHint : undefined,
      linkEpisodeId,
      linkBreakpointKey,
    });

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

      <PromptField
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
      />

      <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
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
        <Select
          label={t('resolution')}
          hint={t('resolutionHint')}
          value={resolution}
          onChange={(event) => setResolution(event.target.value as '2K' | '768P')}
          options={[
            { value: '2K', label: '2K' },
            { value: '768P', label: '768P' },
          ]}
        />
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

  return (
    <GenerationStudioShell
      source={source}
      reference={reference}
      uploads={uploads}
      onUploaded={(asset) => setUploads((current) => [...current, asset])}
      onRemove={removeUpload}
      isPortraitPreview={orientation === 'portrait'}
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
