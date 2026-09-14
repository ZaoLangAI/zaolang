'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { VideoFirstFrame } from '@/components/media/video-first-frame';
import type { StudioSource } from '@/components/studio/generation-studio-shell';
import { IconButton } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconClose, IconSparkle, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { WorkDetail } from '@/lib/api/types';
import { cn, controlPress } from '@/lib/cn';
import { type Asset, declareConsent, uploadFile } from '@/lib/upload';

// `SUBJECT_MAX_LENGTH` in `app/domain/consent/service.py`.
const CONSENT_SUBJECT_MAX_LENGTH = 255;

/**
 * Left rail of the studio: what the new version inherits, plus anything the
 * user adds.
 *
 * Inherited materials are not removable — they are the licence-bearing part of
 * the remix, and dropping them would break the attribution the lineage
 * promises.
 *
 * An added material that shows a real person needs that person's consent
 * before it may feed a generation (深度合成管理规定 §14): ticking "shows a real
 * person" asks who it is plus an explicit confirmation *before* the upload,
 * flags the upload (`depictsRealPerson`) and records a portrait consent right
 * after it. The confirmation resets after every upload, so each real-person
 * asset gets its own declaration.
 */
export function SourceMaterialRail({
  source,
  reference,
  uploads,
  onUploaded,
  onRemove,
  onSelectUpload,
  hideUpload = false,
}: {
  source?: StudioSource;
  /**
   * A work the prompt was borrowed from. Kept in its own block, visually apart
   * from the source materials, because it carries no licence and contributes
   * nothing to the generation request.
   */
  reference?: WorkDetail;
  uploads: Asset[];
  onUploaded: (asset: Asset) => void;
  onRemove: (assetId: string) => void;
  /** Clicking an uploaded thumbnail — shows it enlarged in the studio's
   * preview area instead of doing nothing. Omitted where there's no preview
   * area to load it into (video/audio don't pass this). */
  onSelectUpload?: (asset: Asset) => void;
  /** Hides the "add material" tile entirely — `AudioGenerationStudio` has
   * its own dedicated voice-clone uploader (a different MIME whitelist and
   * upload `purpose` than this rail's image/video `generation_reference`),
   * so this rail is only ever shown here for an inherited remix source,
   * never as a place to add more material. */
  hideUpload?: boolean;
}) {
  const t = useTranslations('remixPage');
  const tStates = useTranslations('states');
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [realPerson, setRealPerson] = useState(false);
  const [consentSubject, setConsentSubject] = useState('');
  const [consentConfirmed, setConsentConfirmed] = useState(false);

  const sourceMediaType = source?.work.media_type ?? source?.work.current_version?.media_type;
  const inherited = source
    ? sourceMediaType === 'video'
      ? [
          {
            id: 'source-video',
            label: t('sourceVideo'),
            url: source.work.current_version?.media_url ?? source.work.cover_url,
            mediaType: 'video',
          },
        ]
      : [
          {
            id: 'first-frame',
            label: t('firstFrame'),
            url: source.work.current_version?.cover_url ?? source.work.cover_url,
            mediaType: 'image',
          },
          ...(source.params.style_tags ?? []).slice(0, 2).map((tag, index) => ({
            id: `style-${tag}`,
            label: index === 0 ? t('styleReference') : t('lightReference'),
            url: source.work.cover_url,
            mediaType: 'image',
          })),
        ]
    : [];

  const total = inherited.length + uploads.length;
  const consentMissing = realPerson && (!consentSubject.trim() || !consentConfirmed);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const asset = await uploadFile(file, 'generation_reference', {
        depictsRealPerson: realPerson,
      });
      if (realPerson) {
        try {
          await declareConsent(asset.id, { type: 'portrait', subject: consentSubject.trim() });
        } catch {
          // The asset is kept; a submit using it is refused with
          // `ASSET_RIGHTS_REQUIRED` until a consent is recorded.
          notify(t('consentFailed'), 'error');
        }
        setConsentConfirmed(false);
      }
      onUploaded(asset);
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <aside aria-labelledby="source-material-heading" className="lg:border-r lg:border-border lg:pr-4">
      <h2 id="source-material-heading" className="text-sm font-semibold">
        {t('sourceMaterials', { count: total })}
      </h2>
      <p className="mt-1 text-[11px] text-muted">{t('sourceHint')}</p>

      <ul className="mt-4 flex gap-3 overflow-x-auto lg:flex-col lg:overflow-visible">
        {inherited.map((item) => (
          <li key={item.id} className="w-28 shrink-0 lg:w-full">
            <Thumb url={item.url} label={item.label} mediaType={item.mediaType} />
          </li>
        ))}

        {uploads.map((asset) => (
          <li key={asset.id} className="relative w-28 shrink-0 lg:w-full">
            {onSelectUpload ? (
              <button
                type="button"
                onClick={() => onSelectUpload(asset)}
                className={cn('block w-full text-left focus-visible:outline-2', controlPress)}
              >
                <Thumb
                  url={asset.url}
                  label={asset.media_type === 'video' ? t('videoReference') : t('imageReference')}
                  mediaType={asset.media_type}
                />
              </button>
            ) : (
              <Thumb
                url={asset.url}
                label={asset.media_type === 'video' ? t('videoReference') : t('imageReference')}
                mediaType={asset.media_type}
              />
            )}
            <IconButton
              label={`${t('addMaterial')} ✕`}
              size="sm"
              variant="secondary"
              className="absolute right-1.5 top-1.5 size-6 rounded-full"
              onClick={() => onRemove(asset.id)}
            >
              <IconClose className="size-3.5" />
            </IconButton>
          </li>
        ))}

        {hideUpload ? null : (
          <li className="w-28 shrink-0 lg:w-full">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy || uploads.length >= 9 || consentMissing}
              className={cn(
                'flex aspect-[4/3] w-full flex-col items-center justify-center gap-1.5 rounded-[var(--radius-sm)] border border-dashed border-border text-[11px] text-muted hover:border-border-strong hover:text-text disabled:opacity-60',
                controlPress,
              )}
            >
              {busy ? <Spinner className="size-4" /> : <IconUpload className="size-4" />}
              {uploads.length >= 9 ? t('materialLimit') : t('addMaterial')}
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,video/mp4,video/webm"
              aria-label={t('addMaterial')}
              className="sr-only"
              onChange={(event) => void pick(event.target.files?.[0])}
            />
          </li>
        )}
      </ul>

      {hideUpload ? null : (
        <div className="mt-3 flex flex-col gap-2">
          <label className="flex cursor-pointer items-start gap-2 text-[11px] leading-relaxed">
            <input
              type="checkbox"
              checked={realPerson}
              onChange={(event) => setRealPerson(event.target.checked)}
              className="mt-0.5 size-3.5 shrink-0 accent-[var(--primary)]"
            />
            <span>
              {t('depictsRealPerson')}
              <span className="block text-muted">{t('depictsRealPersonHint')}</span>
            </span>
          </label>
          {realPerson ? (
            <>
              <TextInput
                label={t('consentSubjectLabel')}
                hint={t('consentSubjectHint')}
                value={consentSubject}
                maxLength={CONSENT_SUBJECT_MAX_LENGTH}
                required
                onChange={(event) => setConsentSubject(event.target.value)}
              />
              <label className="flex cursor-pointer items-start gap-2 text-[11px] leading-relaxed">
                <input
                  type="checkbox"
                  checked={consentConfirmed}
                  onChange={(event) => setConsentConfirmed(event.target.checked)}
                  className="mt-0.5 size-3.5 shrink-0 accent-[var(--primary)]"
                />
                {t('consentConfirmPortrait')}
              </label>
            </>
          ) : null}
        </div>
      )}

      {reference ? (
        <section className="mt-5 border-t border-border pt-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <IconSparkle className="size-4 text-amber" />
            {t('inspirationReference')}
          </h3>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {t('inspirationReferenceHint')}
          </p>
          <div className="mt-3 w-28 lg:w-full">
            <Thumb
              url={reference.current_version?.cover_url ?? reference.cover_url}
              label={reference.title}
              mediaType="image"
            />
          </div>
          <Link
            href={`/work/${reference.id}`}
            className="mt-2 inline-block text-[11px] text-muted hover:text-text"
          >
            {t('viewSourceWork')}
          </Link>
        </section>
      ) : null}
    </aside>
  );
}

function Thumb({
  url,
  label,
  mediaType = 'image',
}: {
  url?: string | null;
  label: string;
  mediaType?: string;
}) {
  return (
    <figure className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
      <div className="relative aspect-[4/3] bg-surface-soft">
        {url && mediaType === 'video' ? (
          <VideoFirstFrame src={url} label={label} />
        ) : url ? (
          <Image src={url} alt="" fill sizes="160px" className="object-cover" />
        ) : null}
      </div>
      <figcaption className="truncate bg-surface px-2 py-1.5 text-[11px] text-muted">
        {label}
      </figcaption>
    </figure>
  );
}
