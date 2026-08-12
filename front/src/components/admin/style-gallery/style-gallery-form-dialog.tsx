'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, Switch, TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';
import type { StyleGalleryAdminEntry } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { uploadStyleGalleryCover } from '@/lib/admin/upload';

const LANDSCAPE_ASPECTS = ['16:9', '4:3', '21:9'];
const PORTRAIT_ASPECTS = ['9:16', '3:4'];

function paramsToText(params: Record<string, unknown>): string {
  return JSON.stringify(params, null, 2);
}

/**
 * Create/edit form for one system style catalogue entry.
 *
 * `slug` and `is_active` only make sense in one direction each — the slug is
 * the row's identity so it is immutable after creation, and `is_active`
 * has no meaning for a row that does not exist yet (the create endpoint
 * always starts an entry active) — so both are conditionally rendered rather
 * than always shown and sometimes disabled.
 */
export function StyleGalleryFormDialog({
  open,
  onClose,
  entry,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** `null` means create. */
  entry: StyleGalleryAdminEntry | null;
  onSaved: (entry: StyleGalleryAdminEntry) => void;
}) {
  const t = useTranslations('adminStyleGallery');

  return (
    <Dialog open={open} onClose={onClose} title={entry ? t('editTitle') : t('createTitle')} size="lg">
      {/* Keyed on the identity of what is being edited, not just `open`: this
          is what re-seeds every field from `entry` on a fresh mount instead of
          reaching for an effect that calls `setState` on every open. */}
      <StyleGalleryForm key={open ? entry?.id ?? 'create' : 'closed'} entry={entry} onClose={onClose} onSaved={onSaved} />
    </Dialog>
  );
}

function StyleGalleryForm({
  entry,
  onClose,
  onSaved,
}: {
  entry: StyleGalleryAdminEntry | null;
  onClose: () => void;
  onSaved: (entry: StyleGalleryAdminEntry) => void;
}) {
  const t = useTranslations('adminStyleGallery');
  const tAdmin = useTranslations('admin');

  const [slug, setSlug] = useState(entry?.slug ?? '');
  const [labelZh, setLabelZh] = useState(entry?.label_zh ?? '');
  const [labelEn, setLabelEn] = useState(entry?.label_en ?? '');
  const [labelJa, setLabelJa] = useState(entry?.label_ja ?? '');
  const [description, setDescription] = useState(entry?.description ?? '');
  const [aspectRatio, setAspectRatio] = useState(() => {
    const value = entry?.params.aspect_ratio;
    return typeof value === 'string' ? value : '16:9';
  });
  const [paramsText, setParamsText] = useState(() => paramsToText(entry?.params ?? {}));
  const [sortOrder, setSortOrder] = useState(String(entry?.sort_order ?? 0));
  const [isActive, setIsActive] = useState(entry?.is_active ?? true);
  const [coverAssetId, setCoverAssetId] = useState<string | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(entry?.cover_url ?? null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paramsError, setParamsError] = useState<string | null>(null);

  const handleCoverChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const asset = await uploadStyleGalleryCover(file);
      setCoverAssetId(asset.id);
      setCoverPreview(asset.url ?? null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    let params: Record<string, unknown>;
    try {
      const parsed = JSON.parse(paramsText || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('not an object');
      }
      params = { ...parsed, aspect_ratio: aspectRatio };
    } catch {
      setParamsError(t('paramsInvalid'));
      return;
    }
    setParamsError(null);
    setSaving(true);
    setError(null);
    try {
      const payload = {
        label_zh: labelZh.trim(),
        label_en: labelEn.trim(),
        label_ja: labelJa.trim(),
        description: description.trim() || null,
        cover_asset_id: coverAssetId ?? entry?.cover_asset_id ?? null,
        params,
        sort_order: Number(sortOrder) || 0,
      };
      const saved = entry
        ? await adminApi.put<StyleGalleryAdminEntry>(`/v1/admin/style-gallery/${entry.id}`, {
            ...payload,
            is_active: isActive,
          })
        : await adminApi.post<StyleGalleryAdminEntry>('/v1/admin/style-gallery', {
            ...payload,
            slug: slug.trim(),
          });
      onSaved(saved);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setSaving(false);
    }
  };

  const complete =
    (entry !== null || /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(slug.trim())) &&
    labelZh.trim().length > 0 &&
    labelEn.trim().length > 0 &&
    labelJa.trim().length > 0;

  return (
    <div className="flex flex-col gap-4">
      {entry ? null : (
        <TextInput
          label={t('slug')}
          hint={t('slugHint')}
          required
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput
          label={t('labelZh')}
          required
          value={labelZh}
          onChange={(event) => setLabelZh(event.target.value)}
        />
        <TextInput
          label={t('labelEn')}
          required
          value={labelEn}
          onChange={(event) => setLabelEn(event.target.value)}
        />
        <TextInput
          label={t('labelJa')}
          required
          value={labelJa}
          onChange={(event) => setLabelJa(event.target.value)}
        />
      </div>

      <TextArea
        label={t('description')}
        rows={2}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />

      <div>
        <p className="mb-1.5 text-sm font-medium text-text">{t('cover')}</p>
        <div className="flex items-center gap-3">
          <span className="relative block size-20 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft">
            {coverPreview ? (
              <Image src={coverPreview} alt="" fill sizes="80px" className="object-cover" />
            ) : null}
          </span>
          <label className="cursor-pointer rounded-[var(--radius-sm)] border border-border px-3 py-2 text-xs hover:bg-surface-soft">
            {uploading ? tAdmin('loading') : t('coverUpload')}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              disabled={uploading}
              onChange={(event) => void handleCoverChange(event)}
            />
          </label>
        </div>
      </div>

      <Select
        label={t('aspectRatio')}
        value={aspectRatio}
        onChange={(event) => setAspectRatio(event.target.value)}
        options={[...LANDSCAPE_ASPECTS, ...PORTRAIT_ASPECTS].map((value) => ({
          value,
          label: value,
        }))}
      />

      <TextArea
        label={t('params')}
        hint={t('paramsHint')}
        error={paramsError ?? undefined}
        rows={5}
        className="font-mono text-xs"
        value={paramsText}
        onChange={(event) => setParamsText(event.target.value)}
      />

      <TextInput
        label={t('sortOrder')}
        type="number"
        value={sortOrder}
        onChange={(event) => setSortOrder(event.target.value)}
      />

      {entry ? <Switch label={t('isActive')} checked={isActive} onChange={setIsActive} /> : null}

      {error ? <ErrorNotice title={error} /> : null}

      <div className="flex justify-end gap-3 border-t border-border pt-4">
        <Button variant="ghost" onClick={onClose}>
          {tAdmin('reset')}
        </Button>
        <Button disabled={!complete || uploading} loading={saving} onClick={() => void submit()}>
          {tAdmin('save')}
        </Button>
      </div>
    </div>
  );
}
