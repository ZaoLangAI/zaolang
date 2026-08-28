'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { MultiSelect, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { uploadFile } from '@/lib/upload';

import { pascalCase, SERIES_GENRES, TARGET_PLATFORMS } from './format';

/**
 * Create/edit dialog for a `kind=drama` series — the single place series
 * metadata (name, platforms, genre, logo) is entered. New episodes are never
 * created here; they only ever come out of "文案创作" (`/create/script`).
 */
export function SeriesFormDialog({
  open,
  onClose,
  series,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** `null` means create. */
  series: editorApi.DramaSeries | null;
  onSaved: (series: editorApi.DramaSeries) => void;
}) {
  const t = useTranslations('editor');

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={series ? t('seriesEditTitle') : t('seriesCreateTitle')}
      size="lg"
    >
      {/* Keyed on the identity of what is being edited: re-seeds every field
          from `series` on a fresh mount instead of syncing via an effect. */}
      <SeriesForm
        key={open ? (series?.id ?? 'create') : 'closed'}
        series={series}
        onClose={onClose}
        onSaved={onSaved}
      />
    </Dialog>
  );
}

function SeriesForm({
  series,
  onClose,
  onSaved,
}: {
  series: editorApi.DramaSeries | null;
  onClose: () => void;
  onSaved: (series: editorApi.DramaSeries) => void;
}) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');

  const [title, setTitle] = useState(series?.title ?? '');
  const [englishTitle, setEnglishTitle] = useState(series?.english_title ?? '');
  const [plannedCount, setPlannedCount] = useState(
    series?.planned_episode_count ? String(series.planned_episode_count) : '',
  );
  const [platforms, setPlatforms] = useState<string[]>(series?.target_platforms ?? []);
  const [genres, setGenres] = useState<string[]>(series?.genre_tags ?? []);
  const [logoAssetId, setLogoAssetId] = useState<string | null>(series?.logo_asset_id ?? null);
  const [logoPreview, setLogoPreview] = useState<string | null>(series?.logo_url ?? null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleGenre = (value: string) => {
    setGenres((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );
  };

  const handleLogoChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const asset = await uploadFile(file, 'series_logo');
      setLogoAssetId(asset.id);
      setLogoPreview(asset.url ?? null);
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : t('commandFailed'));
    } finally {
      setUploading(false);
    }
  };

  const trimmedTitle = title.trim();
  const complete = trimmedTitle.length > 0 && platforms.length > 0;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        title: trimmedTitle,
        english_title: englishTitle.trim() || undefined,
        planned_episode_count: plannedCount.trim() ? Number(plannedCount) : undefined,
        genre_tags: genres,
        target_platforms: platforms,
        logo_asset_id: logoAssetId ?? undefined,
      };
      const saved = series
        ? await editorApi.updateDramaSeries(series.id, payload)
        : await editorApi.createDramaSeries(payload);
      onSaved(saved);
      onClose();
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : t('commandFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextInput
          label={t('seriesTitle')}
          required
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={saving}
        />
        <TextInput
          label={t('seriesEnglishTitle')}
          value={englishTitle}
          onChange={(event) => setEnglishTitle(event.target.value)}
          disabled={saving}
        />
      </div>

      <TextInput
        label={t('seriesPlannedEpisodeCount')}
        type="number"
        min={1}
        value={plannedCount}
        onChange={(event) => setPlannedCount(event.target.value)}
        disabled={saving}
      />

      <MultiSelect
        label={t('seriesTargetPlatforms')}
        hint={t('seriesTargetPlatformsHint')}
        value={platforms}
        onChange={setPlatforms}
        options={TARGET_PLATFORMS.map((value) => ({
          value,
          label: t(`channel${pascalCase(value)}`),
        }))}
        placeholder={t('seriesTargetPlatformsPlaceholder')}
        disabled={saving}
      />

      <div>
        <p className="mb-1.5 text-sm font-medium text-text">{t('seriesGenreTags')}</p>
        <div className="flex flex-wrap gap-2">
          {SERIES_GENRES.map((genre) => (
            <button
              key={genre}
              type="button"
              onClick={() => toggleGenre(genre)}
              disabled={saving}
              aria-pressed={genres.includes(genre)}
              className={cn(
                'rounded-full border px-3.5 py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                genres.includes(genre)
                  ? 'border-primary bg-primary/12 text-primary'
                  : 'border-border text-muted hover:border-border-strong hover:text-text',
              )}
            >
              {t(`genre${pascalCase(genre)}`)}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-sm font-medium text-text">{t('seriesLogo')}</p>
        <div className="flex items-center gap-3">
          <span className="relative block size-20 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft">
            {logoPreview ? (
              <Image src={logoPreview} alt="" fill sizes="80px" className="object-cover" />
            ) : null}
          </span>
          <label className="cursor-pointer rounded-[var(--radius-sm)] border border-border px-3 py-2 text-xs hover:bg-surface-soft">
            {uploading ? t('dashboardLoading') : t('seriesLogoUpload')}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              disabled={uploading}
              onChange={(event) => void handleLogoChange(event)}
            />
          </label>
        </div>
      </div>

      {error ? <ErrorNotice title={error} /> : null}

      <div className="flex justify-end gap-3 border-t border-border pt-4">
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          {tActions('cancel')}
        </Button>
        <Button disabled={!complete || uploading} loading={saving} onClick={() => void submit()}>
          {tActions('save')}
        </Button>
      </div>
    </div>
  );
}
