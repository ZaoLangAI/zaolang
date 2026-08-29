'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Spinner } from '@/components/ui/spinner';
import { isApiError } from '@/lib/api/errors';
import type { Asset } from '@/lib/upload';

import * as editorApi from './api';

/**
 * Extracted from `media-library-panel.tsx`'s asset grid — this is the
 * "just pick one of my assets" half of that panel, reused wherever a
 * feature needs an `asset_id` (e.g. the brand overlay in
 * `canvas-panel.tsx`) instead of a raw text field the user has to know an
 * ID to fill in. Deliberately does not duplicate insert/sticker/transcribe
 * actions — those stay in the media library, this only ever resolves to a
 * single selected `Asset`.
 */
export function AssetPicker({
  value,
  mediaType,
  disabled,
  triggerLabel,
  onSelect,
}: {
  /** Currently chosen asset id, if any — highlighted in the grid. */
  value?: string | null;
  /** Restricts the grid to one media type (e.g. `"image"` for a still overlay). */
  mediaType?: Asset['media_type'];
  disabled?: boolean;
  triggerLabel: string;
  onSelect: (asset: Asset) => void;
}) {
  const t = useTranslations('editor');
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Asset[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || items !== null) return;
    let cancelled = false;
    editorApi
      .listMyMedia()
      .then((page) => {
        if (!cancelled) setItems(page.items);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      });
    return () => {
      cancelled = true;
    };
  }, [open, items, t]);

  const filtered = items?.filter((asset) => !mediaType || asset.media_type === mediaType) ?? null;

  return (
    <>
      <Button size="sm" variant="secondary" disabled={disabled} onClick={() => setOpen(true)}>
        {triggerLabel}
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t('assetPickerTitle')}
        size="lg"
      >
        {loadError ? (
          <p className="text-xs text-danger">{loadError}</p>
        ) : filtered === null ? (
          <div className="grid place-items-center py-8">
            <Spinner label={t('loading')} />
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-muted">{t('mediaLibraryEmpty')}</p>
        ) : (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {filtered.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  onClick={() => {
                    onSelect(asset);
                    setOpen(false);
                  }}
                  aria-pressed={asset.id === value}
                  className={`flex w-full flex-col overflow-hidden rounded-[var(--radius-sm)] border text-left transition-colors ${
                    asset.id === value
                      ? 'border-primary ring-1 ring-primary'
                      : 'border-border hover:border-primary'
                  }`}
                >
                  <span className="relative flex aspect-video items-center justify-center bg-track">
                    {asset.media_type === 'image' && asset.url ? (
                      // eslint-disable-next-line @next/next/no-img-element -- short-lived signed URL
                      <img
                        src={asset.url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        crossOrigin="anonymous"
                        className="size-full object-cover"
                      />
                    ) : asset.media_type === 'video' && asset.url ? (
                      <video
                        src={asset.url}
                        muted
                        preload="metadata"
                        crossOrigin="anonymous"
                        className="size-full object-cover"
                      />
                    ) : (
                      <span className="text-xs text-muted">{asset.media_type}</span>
                    )}
                  </span>
                  <span className="truncate px-2 py-1 text-[11px] text-muted">
                    {asset.ai_generated ? t('mediaSourceGenerated') : t('mediaSourceUploaded')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
    </>
  );
}
