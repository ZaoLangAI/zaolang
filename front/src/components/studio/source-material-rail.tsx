'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { VideoFirstFrame } from '@/components/media/video-first-frame';
import type { StudioSource } from '@/components/studio/generation-studio-shell';
import { IconClose, IconSparkle, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { WorkDetail } from '@/lib/api/types';
import { type Asset, uploadFile } from '@/lib/upload';

/**
 * Left rail of the studio: what the new version inherits, plus anything the
 * user adds.
 *
 * Inherited materials are not removable — they are the licence-bearing part of
 * the remix, and dropping them would break the attribution the lineage
 * promises.
 */
export function SourceMaterialRail({
  source,
  reference,
  uploads,
  onUploaded,
  onRemove,
  onSelectUpload,
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
}) {
  const t = useTranslations('remixPage');
  const tStates = useTranslations('states');
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

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

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      onUploaded(await uploadFile(file, 'generation_reference'));
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
                className="block w-full text-left focus-visible:outline-2"
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
            <button
              type="button"
              aria-label={`${t('addMaterial')} ✕`}
              onClick={() => onRemove(asset.id)}
              className="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full bg-surface-raised/90 text-muted hover:text-text"
            >
              <IconClose className="size-3.5" />
            </button>
          </li>
        ))}

        <li className="w-28 shrink-0 lg:w-full">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy || uploads.length >= 9}
            className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-1.5 rounded-[var(--radius-sm)] border border-dashed border-border text-[11px] text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-60"
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
      </ul>

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
