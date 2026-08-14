'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { SourceMaterialRail } from '@/components/studio/source-material-rail';
import { OptionGroup } from '@/components/studio/option-group';
import { PromptPolish } from '@/components/studio/prompt-polish';
import { StyleGalleryDialog } from '@/components/studio/style-gallery-dialog';
import { Button } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import {
  IconChevronDown,
  IconClock,
  IconClose,
  IconGear,
  IconLandscape,
  IconMic,
  IconPortrait,
  IconSparkle,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Sheet } from '@/components/ui/sheet';
import { DevicePreview } from '@/components/media/device-preview';
import { Poster } from '@/components/media/poster';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  CreationSkillDetail,
  CreationSkillSummary,
  Page,
  ReusableParams,
  StyleGalleryEntry,
  StylePreset,
  WorkDetail,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount, formatDuration } from '@/lib/format';
import { DEFAULT_DEVICE_ID } from '@/lib/devices';
import { styleGalleryLabel } from '@/lib/style-gallery';
import type { Asset } from '@/lib/upload';
import { useGenerationSubmit } from '@/lib/use-generation-submit';
import { useMinWidth } from '@/lib/use-media-query';
import { useResource } from '@/lib/use-resource';

/** Params this form already has a control for; anything else rides along as `extra`. */
const KNOWN_PRESET_KEYS = new Set(['prompt', 'prompt_suffix', 'aspect_ratio']);

type Tier = 'preview' | 'standard' | 'cinematic';
type Operation =
  | 'text_to_video'
  | 'image_to_video'
  | 'video_to_video'
  | 'text_to_image'
  | 'image_to_image'
  | 'audio_generation';
type ReferenceMode = 'input_references' | 'frame_images';
type Orientation = 'landscape' | 'portrait';

// No `1:1`: every framing the studio offers is either wider or taller than
// square, so orientation is always a meaningful first choice.
const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9'] as const;
const PORTRAIT_ASPECTS = ['9:16', '3:4'] as const;
const ASPECTS = [...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS] as const;
const DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
// Fixed roster, mirrored by `AUDIO_VOICES` in `app/api/schemas/jobs.py` — these
// are the provider's own voice ids, so they travel through untranslated.
const AUDIO_VOICES = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'] as const;
const PORTRAIT_ASPECT = '9:16';
const PROMPT_MAX_LENGTH = 600;

export interface StudioSource {
  work: WorkDetail;
  params: ReusableParams;
}

/**
 * The generation form shared by `/create/new` and `/remix/[workId]`.
 *
 * Both routes submit the same job with the same pricing rules; the only real
 * difference is whether a source work seeds the materials and the prompt. One
 * component means the remix path cannot silently drift from the create path,
 * and the parts a differently shaped shell would still have to repeat live in
 * `use-generation-submit`.
 *
 * The three columns collapse rather than shrink below `lg`: the preview leads,
 * the materials scroll sideways under it, and the parameters move into a bottom
 * sheet with the estimate pinned above the thumb.
 */
export function GenerationStudio({
  operation: initialOperation,
  source,
  reference,
  initialPrompt,
  initialStyleParams,
  initialStyleGalleryId,
}: {
  operation: Operation;
  /** A licensed remix source. Submitted as `source_work_id`. */
  source?: StudioSource;
  /**
   * A work the idea came from, carried over from the discover feed.
   *
   * Never submitted as `source_work_id` and never added to the reference
   * assets: doing either would fabricate a lineage edge that no author
   * authorised, which is exactly what `assert_remixable` exists to prevent.
   */
  reference?: WorkDetail;
  initialPrompt?: string;
  /** A style gallery entry's `params`, applied once on mount (from `?styleId=`). */
  initialStyleParams?: Record<string, unknown>;
  /** The catalogue id behind `initialStyleParams`; submitted as `style_gallery_id`. */
  initialStyleGalleryId?: string;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tGallery = useTranslations('styleGallery');
  const tSkill = useTranslations('skillLibrary');
  const { notify } = useToast();
  const locale = useLocale() as Locale;
  const router = useRouter();

  const [prompt, setPrompt] = useState(source?.params.prompt ?? initialPrompt ?? '');
  const [aspect, setAspect] = useState<string>('16:9');
  const [duration, setDuration] = useState<number>(8);
  const [seed, setSeed] = useState('');
  const [referenceMode, setReferenceMode] = useState<ReferenceMode>('input_references');
  const [firstFrameAssetId, setFirstFrameAssetId] = useState('');
  const [lastFrameAssetId, setLastFrameAssetId] = useState('');
  const [sound, setSound] = useState(true);
  const [voice, setVoice] = useState<string>(AUDIO_VOICES[0]);
  const [tier, setTier] = useState<Tier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [uploads, setUploads] = useState<Asset[]>([]);
  const [paramsRequested, setParamsRequested] = useState(false);
  const [presetId, setPresetId] = useState('');
  const [presetExtra, setPresetExtra] = useState<Record<string, unknown>>({});
  const [skillPickerValue, setSkillPickerValue] = useState('');
  const [styleGalleryOpen, setStyleGalleryOpen] = useState(false);
  const [appliedStyleGalleryId, setAppliedStyleGalleryId] = useState<string | null>(
    initialStyleGalleryId ?? null,
  );
  const [moreSettingsOpen, setMoreSettingsOpen] = useState(false);
  // Distinct from `skillPickerValue` above (which resets after each pick so
  // the picker is ready for the next one): this is the ordered set that
  // actually travels to the job. Up to 5 skills can be combined (mirrors
  // `GenerationParams.skill_ids` server-side cap).
  const [appliedSkillIds, setAppliedSkillIds] = useState<string[]>([]);
  const [pendingUnlockSkill, setPendingUnlockSkill] = useState<CreationSkillSummary | null>(null);

  const { status: sessionStatus } = useSession();
  const publicPresets = useResource<Page<StylePreset>>('/v1/style-presets');
  const minePresets = useResource<Page<StylePreset>>(
    sessionStatus === 'authenticated' ? '/v1/style-presets?mine=true' : null,
  );
  const presets = useMemo(() => {
    const byId = new Map<string, StylePreset>();
    for (const preset of publicPresets.data?.items ?? []) byId.set(preset.id, preset);
    for (const preset of minePresets.data?.items ?? []) byId.set(preset.id, preset);
    return [...byId.values()];
  }, [publicPresets.data, minePresets.data]);

  const publicSkills = useResource<Page<CreationSkillSummary>>('/v1/skills/public');
  const mineSkills = useResource<Page<CreationSkillSummary>>(
    sessionStatus === 'authenticated' ? '/v1/skills' : null,
  );
  const skills = useMemo(() => {
    const byId = new Map<string, CreationSkillSummary>();
    for (const skill of publicSkills.data?.items ?? []) byId.set(skill.id, skill);
    for (const skill of mineSkills.data?.items ?? []) byId.set(skill.id, skill);
    return [...byId.values()];
  }, [publicSkills.data, mineSkills.data]);

  /** Shared by presets and skills: both apply the same `prompt`/`aspect_ratio`/extras shape. */
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

  const applyPreset = (preset: StylePreset) => {
    applyParams(preset.params);
    // Best-effort usage counter; a preset is still fully applied locally if this fails.
    void api.post(`/v1/style-presets/${preset.id}/apply`).catch(() => undefined);
  };

  const applyStyleGalleryEntry = (entry: StyleGalleryEntry) => {
    applyParams(entry.params);
    setAppliedStyleGalleryId(entry.id);
    setStyleGalleryOpen(false);
    // Same best-effort shape as `applyPreset`: the usage counter is a nicety,
    // not a precondition for the pick actually landing in the form.
    void api.post(`/v1/style-gallery/${entry.id}/apply`).catch(() => undefined);
  };

  // Applied once: `initialStyleParams` is a mount-time seed from `?styleId=`,
  // not a value the form keeps tracking, so a functional `useState` initializer
  // (rather than an effect keyed on the prop) is what makes "once" precise.
  const [styleParamsApplied, setStyleParamsApplied] = useState(false);
  if (!styleParamsApplied && initialStyleParams) {
    setStyleParamsApplied(true);
    applyParams(initialStyleParams);
  }

  const countedInitialStyleApply = useRef(false);
  useEffect(() => {
    if (countedInitialStyleApply.current) return;
    if (!initialStyleGalleryId) return;
    if (sessionStatus !== 'authenticated') return;
    if (appliedStyleGalleryId !== initialStyleGalleryId) return;
    countedInitialStyleApply.current = true;
    void api.post(`/v1/style-gallery/${initialStyleGalleryId}/apply`).catch(() => undefined);
  }, [appliedStyleGalleryId, initialStyleGalleryId, sessionStatus]);

  const appliedStyle = useResource<StyleGalleryEntry>(
    appliedStyleGalleryId ? `/v1/style-gallery/${appliedStyleGalleryId}` : null,
  );

  const MAX_APPLIED_SKILLS = 5;

  const applySkill = (skill: CreationSkillSummary) => {
    if (appliedSkillIds.includes(skill.id) || appliedSkillIds.length >= MAX_APPLIED_SKILLS) return;
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlockSkill(skill);
      return;
    }
    void applyUnlockedSkill(skill);
  };

  const applyUnlockedSkill = async (skill: CreationSkillSummary) => {
    try {
      const detail = await api.post<CreationSkillDetail>(`/v1/skills/${skill.id}/apply`);
      applyParams(detail.params ?? {});
      setAppliedSkillIds((current) => [...current, skill.id]);
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tSkill('applyLocked'), 'error');
    }
  };

  const removeSkill = (skillId: string) => {
    setAppliedSkillIds((current) => current.filter((id) => id !== skillId));
  };

  const hasVideoReference = uploads.some((asset) => asset.media_type === 'video');
  const hasImageReference = uploads.some((asset) => asset.media_type === 'image');
  let operation: Operation = initialOperation;
  if (initialOperation === 'text_to_video') {
    if (referenceMode === 'frame_images' && firstFrameAssetId) operation = 'image_to_video';
    else if (hasVideoReference) operation = 'video_to_video';
    else if (source || hasImageReference) operation = 'image_to_video';
  }

  // Neither operation is a video: no duration, no ambient-sound toggle, and
  // (for audio) no aspect ratio — the studio only asks for what the job
  // actually prices and validates on the backend.
  const isAudio = operation === 'audio_generation';
  const isImage = operation === 'text_to_image' || operation === 'image_to_image';
  const isImageEdit = operation === 'image_to_image';
  const isVideo = ['text_to_video', 'image_to_video', 'video_to_video'].includes(operation);
  const showAspect = isImage || isVideo;
  const showDuration = isVideo;
  const showSound = isVideo;
  const effectiveDuration = showDuration ? duration : 0;
  // Derived, not its own state: an independent `orientation` could disagree
  // with `aspect` the moment a preset/skill/style applies one directly, and
  // then the "adjust while rendering" fix for that disagreement would have to
  // run every render. Deriving it removes the disagreement instead.
  const orientation: Orientation = (LANDSCAPE_ASPECTS as readonly string[]).includes(aspect)
    ? 'landscape'
    : 'portrait';
  const aspectOptions = orientation === 'landscape' ? LANDSCAPE_ASPECTS : PORTRAIT_ASPECTS;
  const imageUploads = uploads.filter((asset) => asset.media_type === 'image');
  const parsedSeed = seed.trim() ? Number(seed) : undefined;
  const seedValid =
    parsedSeed === undefined ||
    (Number.isInteger(parsedSeed) && parsedSeed >= 0 && parsedSeed <= 2 ** 31 - 1);

  const { quote, quoteFailed, submitting, error, submit } = useGenerationSubmit(
    { operation, qualityTier: tier, durationSeconds: effectiveDuration },
    { label: t('submit') },
  );

  // The sheet is the narrow layout's third column. Derived rather than closed
  // in an effect: at `lg` those controls are on the page, so "open" is not a
  // state the wide layout can be in at all.
  const isDesktop = useMinWidth('lg');
  const paramsOpen = paramsRequested && !isDesktop;

  const tierOptions = useMemo(
    () => [
      { value: 'preview' as const, label: t('tierPreview'), hint: t('tierPreviewDesc') },
      { value: 'standard' as const, label: t('tierStandard'), hint: t('tierStandardDesc') },
      { value: 'cinematic' as const, label: t('tierCinematic'), hint: t('tierCinematicDesc') },
    ],
    [t],
  );

  const frameSelectionValid =
    !isVideo || referenceMode !== 'frame_images' || Boolean(firstFrameAssetId);
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
      durationSeconds: effectiveDuration,
      prompt: prompt.trim(),
      aspectRatio: aspect,
      seed: parsedSeed,
      referenceAssetIds:
        isVideo && referenceMode === 'frame_images' ? [] : uploads.map((asset) => asset.id),
      videoOptions: isVideo
        ? {
            resolution: '2K',
            reference_mode: referenceMode,
            first_frame_asset_id:
              referenceMode === 'frame_images' ? firstFrameAssetId || null : null,
            last_frame_asset_id: referenceMode === 'frame_images' ? lastFrameAssetId || null : null,
          }
        : undefined,
      extra: isAudio ? { voice, ...presetExtra } : { sound, ...presetExtra },
      skillIds: appliedSkillIds,
      styleGalleryId: appliedStyleGalleryId ?? undefined,
      sourceWorkId: source?.work.id,
      maxCredits: quote?.credits,
      draftTitle: source?.work.title ?? null,
    });

  const cover = source?.work.current_version?.cover_url ?? source?.work.cover_url;
  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  // One element rendered in two slots: the wide layout's aside and the narrow
  // layout's sheet. Only one of them is ever visible, so the controls stay
  // bound to a single piece of state either way.
  const paramsPanel = (
    <>
      <div>
        <Button
          variant="secondary"
          icon={<IconSparkle className="size-4" />}
          onClick={() => setStyleGalleryOpen(true)}
          className="w-full"
        >
          {tGallery('trigger')}
        </Button>
        {appliedStyleGalleryId ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setAppliedStyleGalleryId(null)}
              className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/12 py-0.5 pl-0.5 pr-2 text-xs font-medium text-primary"
            >
              <Poster
                src={appliedStyle.data?.cover_url}
                alt=""
                aspect="square"
                className="h-6 w-6 shrink-0 rounded"
              />
              {appliedStyle.data
                ? styleGalleryLabel(appliedStyle.data, locale)
                : tGallery('trigger')}
              <IconClose className="h-3 w-3" />
            </button>
          </div>
        ) : null}
      </div>

      {presets.length > 0 ? (
        <Select
          label={t('stylePreset')}
          hint={t('stylePresetHint')}
          value={presetId}
          onChange={(event) => {
            const value = event.target.value;
            const preset = presets.find((item) => item.id === value);
            if (preset) applyPreset(preset);
            // Transient: applying is a one-shot merge, not a persistent choice
            // the form keeps tracking, so the control resets to let the same
            // preset be reapplied after further edits.
            setPresetId('');
          }}
          options={[
            { value: '', label: t('stylePresetNone') },
            ...presets.map((preset) => ({ value: preset.id, label: preset.name })),
          ]}
        />
      ) : null}

      {skills.length > 0 ? (
        <div>
          <Select
            label={t('skillPreset')}
            hint={t('skillPresetHint')}
            value={skillPickerValue}
            onChange={(event) => {
              const value = event.target.value;
              const skill = skills.find((item) => item.id === value);
              if (skill) applySkill(skill);
              // Transient, same reasoning as the style preset select above.
              setSkillPickerValue('');
            }}
            options={[
              { value: '', label: t('skillPresetNone') },
              // Already-applied skills and ones not built for this operation
              // (e.g. a video-only skill while composing an image) don't
              // clutter the picker — `applicable_operations` empty means any.
              ...skills
                .filter(
                  (skill) =>
                    !appliedSkillIds.includes(skill.id) &&
                    (!skill.applicable_operations ||
                      skill.applicable_operations.length === 0 ||
                      skill.applicable_operations.includes(operation)),
                )
                .map((skill) => ({
                  value: skill.id,
                  label:
                    skill.access_credits > 0 && !skill.viewer_unlocked
                      ? `${skill.title} · ${tSkill('priceCredits', { credits: skill.access_credits })}`
                      : skill.title,
                })),
            ]}
          />
          {appliedSkillIds.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {appliedSkillIds.flatMap((id) => {
                const skill = skills.find((item) => item.id === id);
                if (!skill) return [];
                return [
                  <button
                    key={id}
                    type="button"
                    onClick={() => removeSkill(id)}
                    className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/12 py-0.5 pl-0.5 pr-2 text-xs font-medium text-primary"
                  >
                    {/* A real preview, not just a label, so picking a skill shows
                        what it actually does before the job even runs — and a
                        video-based skill plays instead of a broken frame. */}
                    <Poster
                      src={skill.cover_url}
                      alt=""
                      aspect="square"
                      mediaType={skill.cover_media_type}
                      className="h-6 w-6 shrink-0 rounded"
                    />
                    {skill.title}
                    <IconClose className="h-3 w-3" />
                  </button>,
                ];
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div>
        <TextArea
          label={t('promptLabel')}
          placeholder={t('promptPlaceholder')}
          value={prompt}
          maxLength={PROMPT_MAX_LENGTH}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <p className="tabular mt-1 text-right text-[11px] text-muted">
          {prompt.length}/{PROMPT_MAX_LENGTH}
        </p>
        {isVideo ? (
          <PromptPolish
            className="mt-2"
            endpoint="/v1/generation/prompts/enhance"
            prompt={prompt}
            onAccept={setPrompt}
          />
        ) : null}
      </div>

      {isImageEdit ? <p className="text-xs text-muted">{t('referenceRequiredHint')}</p> : null}

      {showAspect ? (
        <>
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
        </>
      ) : null}

      {showDuration ? (
        <OptionGroup
          label={t('duration')}
          value={duration}
          onChange={setDuration}
          options={DURATIONS.map((value) => ({
            value,
            label: t('durationSeconds', { count: value }),
          }))}
        />
      ) : null}

      {isVideo ? (
        <>
          <div className="rounded-[var(--radius-sm)] border border-border">
            <button
              type="button"
              onClick={() => setMoreSettingsOpen((current) => !current)}
              aria-expanded={moreSettingsOpen}
              className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-sm font-medium"
            >
              <span className="flex items-center gap-2">
                <IconGear className="size-4 text-muted" />
                {t('moreSettings')}
              </span>
              <IconChevronDown
                className={cn(
                  'size-4 text-muted transition-transform',
                  moreSettingsOpen && 'rotate-180',
                )}
              />
            </button>
            {moreSettingsOpen ? (
              <div className="flex flex-col gap-4 border-t border-border p-3">
                <Select
                  label={t('resolution')}
                  hint={t('resolutionHint')}
                  value="2K"
                  disabled
                  options={[{ value: '2K', label: '2K' }]}
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
              </div>
            ) : null}
          </div>
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
        </>
      ) : null}

      {showSound ? (
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
      ) : null}

      {isAudio ? (
        <Select
          label={t('voice')}
          hint={t('voiceHint')}
          value={voice}
          onChange={(event) => setVoice(event.target.value)}
          options={AUDIO_VOICES.map((value) => ({
            value,
            label: value.charAt(0).toUpperCase() + value.slice(1),
          }))}
        />
      ) : null}

      <OptionGroup
        label={t('quality')}
        value={tier}
        onChange={setTier}
        options={tierOptions.map((option) => ({
          ...option,
          trailing: quote && option.value === tier ? `${quote.credits}+` : undefined,
        }))}
      />

      <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
        <input
          type="checkbox"
          checked={rightsConfirmed}
          onChange={(event) => setRightsConfirmed(event.target.checked)}
          className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
        />
        {t('rightsConfirm')}
      </label>

      {quoteFailed ? (
        <ErrorNotice title={t('quoteFailed')} />
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
          <div>
            <p className="flex items-center gap-1.5 text-xs">
              <IconClock className="size-3.5 text-muted" />
              {estimate}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">{t('estimateHint')}</p>
          </div>
          <p className="tabular shrink-0 text-sm font-semibold text-amber">{price}</p>
        </div>
      )}

      {quote && !quote.sufficient ? (
        <ErrorNotice
          title={tCredits('insufficient')}
          action={
            <Button size="sm" variant="secondary" onClick={() => router.push('/billing')}>
              {tCredits('manage')}
            </Button>
          }
        />
      ) : null}

      {error ? <ErrorNotice title={error} /> : null}
    </>
  );

  return (
    <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[184px_minmax(0,1fr)_340px]">
      <div className="order-2 min-w-0 lg:order-none">
        <SourceMaterialRail
          source={source}
          reference={reference}
          uploads={uploads}
          onUploaded={(asset) => setUploads((current) => [...current, asset])}
          onRemove={removeUpload}
        />
      </div>

      <div className="order-1 flex min-w-0 flex-col gap-4 lg:order-none">
        {isAudio ? (
          // No frame to preview here — audio has no picture, so the slot that
          // would show one becomes a plain hint instead of an empty poster.
          <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft text-muted">
            <IconMic className="size-8" />
            <p className="text-xs">{t('audioPreviewHint')}</p>
          </div>
        ) : aspect === PORTRAIT_ASPECT ? (
          // A vertical framing is the one the author cannot judge from a
          // 16:9 box, so that is where the phone frame earns its place.
          <DevicePreview
            poster={cover}
            title={source?.work.title ?? t('promptLabel')}
            defaultDeviceId={DEFAULT_DEVICE_ID}
            maxHeight={480}
          />
        ) : (
          <Poster
            src={cover}
            alt={source?.work.title ?? t('promptLabel')}
            aspect="video"
            className="border border-border"
          />
        )}

        {source ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-1.5 text-success">
              <IconSparkle className="size-4" />
              {t('keepAttribution')}
            </span>
            <span className="text-muted">
              {source.work.author.display_name}
              {source.work.license ? ` · ${source.work.license.attribution_text}` : ''}
            </span>
          </div>
        ) : null}

        <div className="flex gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
          <IconSparkle className="size-5 shrink-0 text-amber" />
          <div>
            <p className="text-sm font-medium">{t('directHint')}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{t('directHintBody')}</p>
          </div>
        </div>
      </div>

      <aside
        aria-labelledby="generation-params-heading"
        className="order-3 hidden flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4 lg:flex"
      >
        <h2 id="generation-params-heading" className="text-sm font-semibold">
          {t('howToGenerate')}
        </h2>
        {paramsPanel}
        <Button
          size="lg"
          onClick={runSubmit}
          disabled={!canSubmit}
          loading={submitting}
          icon={<IconSparkle className="size-5" />}
        >
          {submitting ? t('submitting') : t('submit')}
        </Button>
      </aside>

      {/* Keeps the end of the page clear of the fixed bar below. */}
      <div aria-hidden="true" className="safe-mb order-4 h-24 lg:hidden" />

      <div className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface lg:hidden">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-3">
          {error && !paramsOpen ? (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex items-center justify-between gap-3 text-xs">
            <p className="tabular font-semibold text-amber">{price}</p>
            <p className="tabular flex items-center gap-1.5 text-muted">
              <IconClock className="size-3.5" />
              {estimate}
            </p>
          </div>
          {/* The submit button takes the rest of the row rather than sizing to
              its label: it is the only control here that spends credits, and
              the label is the longest string in three languages. */}
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => setParamsRequested(true)}
              icon={<IconGear className="size-4" />}
              className="shrink-0"
            >
              {t('adjustParams')}
            </Button>
            <Button
              onClick={runSubmit}
              disabled={!canSubmit}
              loading={submitting}
              icon={<IconSparkle className="size-4" />}
              className="min-w-0 flex-1"
            >
              {submitting ? t('submitting') : t('submit')}
            </Button>
          </div>
        </div>
      </div>

      <Sheet
        open={paramsOpen}
        onClose={() => setParamsRequested(false)}
        title={t('howToGenerate')}
        description={t('adjustParamsHint')}
        footer={
          <Button variant="secondary" fullWidth onClick={() => setParamsRequested(false)}>
            {t('paramsDone')}
          </Button>
        }
      >
        {paramsPanel}
      </Sheet>

      <StyleGalleryDialog
        open={styleGalleryOpen}
        onClose={() => setStyleGalleryOpen(false)}
        onSelect={applyStyleGalleryEntry}
      />

      <UnlockDialog
        open={pendingUnlockSkill !== null}
        onClose={() => setPendingUnlockSkill(null)}
        path={pendingUnlockSkill ? `/v1/skills/${pendingUnlockSkill.id}/unlock` : '/v1/skills'}
        credits={pendingUnlockSkill?.access_credits ?? 0}
        title={tSkill('unlock')}
        confirm={tSkill('unlockConfirm', {
          credits: pendingUnlockSkill?.access_credits ?? 0,
          title: pendingUnlockSkill?.title ?? '',
        })}
        onUnlocked={() => {
          const skill = pendingUnlockSkill;
          setPendingUnlockSkill(null);
          if (skill) void applyUnlockedSkill({ ...skill, viewer_unlocked: true });
        }}
      />
    </div>
  );
}
