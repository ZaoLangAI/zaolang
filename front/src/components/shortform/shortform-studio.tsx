'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { DevicePreview } from '@/components/media/device-preview';
import {
  CaptionComposer,
  EMPTY_CAPTION,
  type Caption,
} from '@/components/shortform/caption-composer';
import {
  CompliancePanel,
  blockingChecks,
  usePreflightChecks,
} from '@/components/shortform/compliance-panel';
import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconClock, IconSparkle, IconVolume, IconVolumeOff } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character, Series, SeriesDetail, ShortformProfiles } from '@/lib/api/types';
import { DEFAULT_DEVICE_ID } from '@/lib/devices';
import { formatCount, formatDuration } from '@/lib/format';
import { chromeOf, durationOptions, isPortrait } from '@/lib/shortform';
import { useGenerationSubmit } from '@/lib/use-generation-submit';

type Tier = 'preview' | 'standard' | 'cinematic';

const PROMPT_MAX_LENGTH = 600;

/**
 * The vertical studio.
 *
 * Everything the ordinary studio leaves to the author — the framing, the length,
 * the caption — is decided here by the delivery spec the API serves, because a
 * clip that misses the destination app's requirements has to be paid for twice.
 * Quoting, the login wall, the draft and the idempotent submit are not
 * re-implemented: they come from `useGenerationSubmit`, which is what keeps this
 * shell from drifting away from `/create/new`.
 */
export function ShortformStudio({
  profiles,
  series,
  characters,
}: {
  profiles: ShortformProfiles;
  /** `null` means the visitor is signed out — the whole section stays hidden. */
  series: Series[] | null;
  characters: Character[] | null;
}) {
  const t = useTranslations('shortform');
  const tRemix = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { requireAuth } = useSession();

  const catalogue = profiles.profiles;
  const [profileKey, setProfileKey] = useState(
    () =>
      catalogue.find((item) => item.key === profiles.default_profile)?.key ??
      catalogue[0]?.key ??
      '',
  );
  const profile = catalogue.find((item) => item.key === profileKey) ?? catalogue[0]!;

  const durations = useMemo(() => durationOptions(profile), [profile]);
  const [duration, setDuration] = useState(() => durations[1] ?? durations[0]!);
  const [prompt, setPrompt] = useState('');
  // Holds the pre-enhance text so a single "undo" can restore it; cleared as
  // soon as the author edits the field themselves, since the offer to revert
  // to a version they have since typed over would be misleading.
  const [previousPrompt, setPreviousPrompt] = useState<string | null>(null);
  const [enhancing, setEnhancing] = useState(false);
  const [enhanceError, setEnhanceError] = useState<string | null>(null);
  const [sound, setSound] = useState(true);
  const [tier, setTier] = useState<Tier>('standard');
  const [caption, setCaption] = useState<Caption>(EMPTY_CAPTION);
  const [rightsConfirmed, setRightsConfirmed] = useState(false);

  const [seriesList, setSeriesList] = useState<Series[]>(series ?? []);
  const [characterLibrary] = useState<Character[]>(characters ?? []);
  const [seriesId, setSeriesId] = useState('');
  const [episodeNumber, setEpisodeNumber] = useState<number | null>(null);
  const [selectedCharacterIds, setSelectedCharacterIds] = useState<string[]>([]);
  const [newSeriesTitle, setNewSeriesTitle] = useState('');
  const [creatingSeries, setCreatingSeries] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [addCharacterId, setAddCharacterId] = useState('');
  const [addingCharacter, setAddingCharacter] = useState(false);

  // The cast and next episode number depend on the chosen series, so they are
  // fetched fresh rather than trusted from the (lighter) list the page loaded.
  // Keyed by series id so a stale response for a series the author already
  // switched away from is never mistaken for the current one, and bumping
  // `reloadToken` forces a refetch after the cast changes.
  const [seriesDetail, setSeriesDetail] = useState<{ seriesId: string; data: SeriesDetail } | null>(
    null,
  );
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!seriesId) return;
    let cancelled = false;
    api
      .get<SeriesDetail>(`/v1/series/${seriesId}`)
      .then((data) => {
        if (!cancelled) setSeriesDetail({ seriesId, data });
      })
      .catch(() => {
        if (!cancelled) setSeriesError(tStates('errorHint'));
      });
    return () => {
      cancelled = true;
    };
  }, [seriesId, reloadToken, tStates]);

  const currentSeriesDetail = seriesDetail?.seriesId === seriesId ? seriesDetail.data : null;
  const loadingSeriesDetail = seriesId !== '' && currentSeriesDetail === null;

  // Editable fields are re-seeded from the fetched detail exactly once per
  // series switch, tracked here rather than in an effect so the switch lands
  // in the same render as the fetch resolving instead of one paint later.
  const [syncedSeriesId, setSyncedSeriesId] = useState('');
  if (currentSeriesDetail && syncedSeriesId !== seriesId) {
    setSyncedSeriesId(seriesId);
    setEpisodeNumber(currentSeriesDetail.next_episode_number);
    setSelectedCharacterIds(
      (currentSeriesDetail.characters ?? []).map((character) => character.id),
    );
  }

  // Switching spec can leave a length the new one refuses. Adjusted while
  // rendering rather than in an effect: the stale value must never reach the
  // quote, and an effect would let it through for one paint.
  if (!durations.includes(duration)) setDuration(durations[0]!);

  const { quote, quoteFailed, submitting, error, fieldErrors, submit } = useGenerationSubmit(
    { operation: 'text_to_video', qualityTier: tier, durationSeconds: duration },
    { label: t('submit') },
  );

  const checks = usePreflightChecks({
    profile,
    aspectRatio: profile.aspect_ratio,
    durationSeconds: duration,
    title: caption.title,
    description: caption.description,
    hashtags: caption.hashtags,
  });
  const blocking = blockingChecks(checks);

  const canSubmit =
    prompt.trim().length > 0 &&
    rightsConfirmed &&
    blocking.length === 0 &&
    !submitting &&
    (quote?.sufficient ?? true);

  const runSubmit = () =>
    submit({
      operation: 'text_to_video',
      qualityTier: tier,
      durationSeconds: duration,
      prompt: prompt.trim(),
      aspectRatio: profile.aspect_ratio,
      referenceAssetIds: [],
      characterIds: seriesId ? selectedCharacterIds : [],
      extra: { sound },
      maxCredits: quote?.credits,
      shortformProfile: profile.key,
      draftTitle: caption.title.trim() || null,
      // The caption outlives the job on the draft, so the export step after
      // publishing starts from what was written here instead of a blank form.
      draftParams: {
        shortform_caption: {
          title: caption.title.trim(),
          description: caption.description.trim(),
          hashtags: caption.hashtags,
        },
        ...(seriesId ? { series_id: seriesId, episode_number: episodeNumber } : undefined),
      },
    });

  const handleEnhance = () =>
    requireAuth({
      label: t('promptEnhance'),
      run: async () => {
        setEnhancing(true);
        setEnhanceError(null);
        try {
          const result = await api.post<{ prompt: string; degraded: boolean }>(
            '/v1/shortform/prompt/enhance',
            { prompt: prompt.trim() },
          );
          setPreviousPrompt(prompt);
          setPrompt(result.prompt);
        } catch (caught) {
          setEnhanceError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
        } finally {
          setEnhancing(false);
        }
      },
    });

  const handleUndoEnhance = () => {
    if (previousPrompt === null) return;
    setPrompt(previousPrompt);
    setPreviousPrompt(null);
  };

  const handleCreateSeries = () =>
    requireAuth({
      label: t('seriesCreate'),
      run: async () => {
        const title = newSeriesTitle.trim();
        if (!title) return;
        setCreatingSeries(true);
        setSeriesError(null);
        try {
          const created = await api.post<Series>('/v1/series', { title });
          setSeriesList((current) => [created, ...current]);
          setSeriesId(created.id);
          setNewSeriesTitle('');
        } catch (caught) {
          setSeriesError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
        } finally {
          setCreatingSeries(false);
        }
      },
    });

  const handleAddCharacterToSeries = async () => {
    if (!seriesId || !addCharacterId) return;
    setAddingCharacter(true);
    setSeriesError(null);
    try {
      await api.post(`/v1/series/${seriesId}/characters`, { character_id: addCharacterId });
      setSelectedCharacterIds((current) => Array.from(new Set([...current, addCharacterId])));
      setAddCharacterId('');
      setReloadToken((token) => token + 1);
    } catch (caught) {
      setSeriesError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setAddingCharacter(false);
    }
  };

  const toggleCharacter = (characterId: string) => {
    setSelectedCharacterIds((current) =>
      current.includes(characterId)
        ? current.filter((id) => id !== characterId)
        : [...current, characterId],
    );
  };

  const addableCharacters = characterLibrary.filter(
    (character) => !(currentSeriesDetail?.characters ?? []).some((cast) => cast.id === character.id),
  );

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';

  const tierOptions = [
    { value: 'preview' as const, label: tRemix('tierPreview'), hint: tRemix('tierPreviewDesc') },
    { value: 'standard' as const, label: tRemix('tierStandard'), hint: tRemix('tierStandardDesc') },
    {
      value: 'cinematic' as const,
      label: tRemix('tierCinematic'),
      hint: tRemix('tierCinematicDesc'),
    },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-6 lg:grid lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
      <div className="flex min-w-0 flex-col gap-3 lg:sticky lg:top-20 lg:self-start">
        <DevicePreview
          title={t('previewTitle')}
          defaultDeviceId={DEFAULT_DEVICE_ID}
          maxHeight={520}
          chrome={chromeOf(profile)}
          overlay={<CaptionOverlay caption={caption} rightInset={profile.safe_area_right_pct} />}
        />
        <p className="text-xs leading-relaxed text-muted">{t('previewHint')}</p>
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        {series !== null ? (
          <section className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">{t('seriesTitle')}</h2>
              <Link
                href="/create/characters"
                className="text-xs text-muted underline-offset-4 hover:text-text hover:underline"
              >
                {t('manageCharacters')}
              </Link>
            </div>
            <p className="text-[11px] text-muted">{t('seriesHint')}</p>

            {seriesList.length > 0 ? (
              <Select
                label={t('seriesLabel')}
                value={seriesId}
                onChange={(event) => setSeriesId(event.target.value)}
                options={[
                  { value: '', label: t('seriesNone') },
                  ...seriesList.map((item) => ({ value: item.id, label: item.title })),
                ]}
              />
            ) : null}

            <div className="flex items-end gap-2">
              <TextInput
                label={t('seriesNewLabel')}
                placeholder={t('seriesNewPlaceholder')}
                value={newSeriesTitle}
                maxLength={200}
                onChange={(event) => setNewSeriesTitle(event.target.value)}
                className="flex-1"
              />
              <Button
                variant="secondary"
                disabled={newSeriesTitle.trim().length === 0 || creatingSeries}
                loading={creatingSeries}
                onClick={handleCreateSeries}
              >
                {t('seriesCreate')}
              </Button>
            </div>

            {seriesId ? (
              loadingSeriesDetail ? (
                <p className="text-xs text-muted">{tStates('loading')}</p>
              ) : (
                <>
                  <TextInput
                    label={t('episodeLabel')}
                    type="number"
                    min={1}
                    value={episodeNumber ?? ''}
                    onChange={(event) =>
                      setEpisodeNumber(event.target.value ? Number(event.target.value) : null)
                    }
                  />

                  <div>
                    <p className="text-sm font-medium text-text">{t('castLabel')}</p>
                    {currentSeriesDetail && (currentSeriesDetail.characters?.length ?? 0) > 0 ? (
                      <ul className="mt-2 flex flex-col gap-1.5">
                        {(currentSeriesDetail.characters ?? []).map((character) => (
                          <li key={character.id}>
                            <label className="flex cursor-pointer items-center gap-2.5 text-sm">
                              <input
                                type="checkbox"
                                checked={selectedCharacterIds.includes(character.id)}
                                onChange={() => toggleCharacter(character.id)}
                                className="size-4 shrink-0 accent-[var(--primary)]"
                              />
                              {character.name}
                            </label>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 text-xs text-muted">{t('castEmpty')}</p>
                    )}
                  </div>

                  {addableCharacters.length > 0 ? (
                    <div className="flex items-end gap-2">
                      <Select
                        label={t('addCharacterLabel')}
                        value={addCharacterId}
                        onChange={(event) => setAddCharacterId(event.target.value)}
                        options={[
                          { value: '', label: t('addCharacterPlaceholder') },
                          ...addableCharacters.map((character) => ({
                            value: character.id,
                            label: character.name,
                          })),
                        ]}
                      />
                      <Button
                        variant="secondary"
                        disabled={!addCharacterId || addingCharacter}
                        loading={addingCharacter}
                        onClick={() => void handleAddCharacterToSeries()}
                      >
                        {t('addCharacterAction')}
                      </Button>
                    </div>
                  ) : null}
                </>
              )
            ) : null}

            {seriesError ? (
              <p role="alert" className="text-xs text-danger">
                {seriesError}
              </p>
            ) : null}
          </section>
        ) : null}

        <section className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('shotTitle')}</h2>

          <div>
            <TextArea
              label={t('promptLabel')}
              placeholder={t('promptPlaceholder')}
              value={prompt}
              maxLength={PROMPT_MAX_LENGTH}
              onChange={(event) => {
                setPrompt(event.target.value);
                setPreviousPrompt(null);
              }}
            />
            <div className="mt-1 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<IconSparkle className="size-4" />}
                  disabled={prompt.trim().length === 0 || enhancing}
                  loading={enhancing}
                  onClick={handleEnhance}
                >
                  {enhancing ? t('promptEnhancing') : t('promptEnhance')}
                </Button>
                {previousPrompt !== null ? (
                  <Button size="sm" variant="ghost" onClick={handleUndoEnhance}>
                    {t('promptEnhanceUndo')}
                  </Button>
                ) : null}
              </div>
              <p className="tabular shrink-0 text-right text-[11px] text-muted">
                {prompt.length}/{PROMPT_MAX_LENGTH}
              </p>
            </div>
            {enhanceError ? (
              <p role="alert" className="mt-1 text-xs text-danger">
                {enhanceError}
              </p>
            ) : null}
          </div>

          {catalogue.length > 1 ? (
            <div>
              <OptionGroup
                label={t('specLabel')}
                value={profile.key}
                onChange={setProfileKey}
                columns={2}
                options={catalogue.map((item) => ({
                  value: item.key,
                  label: item.aspect_ratio,
                  hint: isPortrait(item) ? t('specPortrait') : t('specLandscape'),
                }))}
              />
              {fieldErrors['params.shortform_profile'] ? (
                <p role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors['params.shortform_profile']}
                </p>
              ) : null}
            </div>
          ) : null}

          <p className="text-[11px] text-muted">
            {t('specHint', {
              width: profile.width,
              height: profile.height,
              min: profile.min_duration_seconds,
              max: profile.max_duration_seconds,
            })}
          </p>

          <div>
            <OptionGroup
              label={tRemix('duration')}
              value={duration}
              onChange={setDuration}
              options={durations.map((value) => ({
                value,
                label: tRemix('durationSeconds', { count: value }),
              }))}
            />
            {fieldErrors['params.duration_seconds'] ? (
              <p role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors['params.duration_seconds']}
              </p>
            ) : null}
          </div>

          <OptionGroup
            label={tRemix('sound')}
            value={sound ? 'on' : 'off'}
            onChange={(value) => setSound(value === 'on')}
            columns={2}
            options={[
              {
                value: 'off',
                label: tRemix('soundOff'),
                icon: <IconVolumeOff className="size-4" />,
              },
              {
                value: 'on',
                label: tRemix('soundAmbient'),
                icon: <IconVolume className="size-4" />,
              },
            ]}
          />

          <OptionGroup
            label={tRemix('quality')}
            value={tier}
            onChange={setTier}
            options={tierOptions.map((option) => ({
              ...option,
              trailing: quote && option.value === tier ? `${quote.credits}+` : undefined,
            }))}
          />
        </section>

        <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('captionTitle')}</h2>
          <p className="mt-1 text-xs text-muted">{t('captionHint')}</p>
          <CaptionComposer
            profile={profile}
            value={caption}
            onChange={setCaption}
            fieldErrors={fieldErrors}
            className="mt-4"
          />
        </section>

        <CompliancePanel
          items={checks}
          title={t('complianceTitle')}
          hint={t('compliancePreflightHint')}
        />

        <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
          <input
            type="checkbox"
            checked={rightsConfirmed}
            onChange={(event) => setRightsConfirmed(event.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
          />
          {tRemix('rightsConfirm')}
        </label>

        {quoteFailed ? (
          <ErrorNotice title={tRemix('quoteFailed')} />
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
            <div>
              <p className="flex items-center gap-1.5 text-xs">
                <IconClock className="size-3.5 text-muted" />
                {estimate}
              </p>
              <p className="mt-0.5 text-[11px] text-muted">{tRemix('estimateHint')}</p>
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

        <Button
          size="lg"
          onClick={runSubmit}
          disabled={!canSubmit}
          loading={submitting}
          icon={<IconSparkle className="size-5" />}
          className="hidden lg:inline-flex"
        >
          {submitting ? t('submitting') : t('submit')}
        </Button>
      </div>

      {/* Keeps the end of the page clear of the fixed bar below. */}
      <div aria-hidden="true" className="safe-mb h-24 lg:hidden" />

      <div className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface lg:hidden">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-3">
          <div className="flex items-center justify-between gap-3 text-xs">
            <p className="tabular font-semibold text-amber">{price}</p>
            <p className="tabular flex items-center gap-1.5 text-muted">
              <IconClock className="size-3.5" />
              {estimate}
            </p>
          </div>
          <Button
            fullWidth
            onClick={runSubmit}
            disabled={!canSubmit}
            loading={submitting}
            icon={<IconSparkle className="size-4" />}
          >
            {submitting ? t('submitting') : t('submit')}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * The caption as the destination app will draw it: bottom left, clear of the
 * interaction rail. Sitting on the screen rather than beside it is the point —
 * a title that reads fine in a form can still be two lines under a like button.
 */
function CaptionOverlay({ caption, rightInset }: { caption: Caption; rightInset: number }) {
  const title = caption.title.trim();
  const tags = caption.hashtags;
  if (title.length === 0 && tags.length === 0) return null;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-0 left-0 flex flex-col gap-1 bg-gradient-to-t from-black/70 to-transparent px-3 pb-3 pt-8 text-white"
      style={{ right: `${rightInset}%` }}
    >
      {title ? <p className="line-clamp-3 text-xs font-semibold leading-snug">{title}</p> : null}
      {tags.length > 0 ? (
        <p className="line-clamp-2 text-[10px] leading-snug text-white/85">
          {tags.map((tag) => `#${tag}`).join(' ')}
        </p>
      ) : null}
    </div>
  );
}
