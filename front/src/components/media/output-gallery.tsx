'use client';

import { useCallback, useState } from 'react';

import { DevicePreview } from '@/components/media/device-preview';
import { cn } from '@/lib/cn';
import { refreshAssetUrl } from '@/lib/refresh-media-src';

/**
 * A job's preview area for more than one output — a multi-view `CHARACTER`
 * job's front/side/back images today, generically any `output_urls` with
 * more than one entry (see `zaolang-generation-jobs`'s multi-output
 * invariant). Falls back to a single `DevicePreview`/`<audio>` element when
 * there is only one output, so this only ever adds a thumbnail strip rather
 * than changing the single-output layout.
 */
export function OutputGallery({
  urls,
  assetIds,
  mediaType,
  title,
  labels,
  itemLabel,
  maxHeight,
}: {
  urls: string[];
  assetIds?: (string | null)[] | null;
  mediaType: 'image' | 'video' | 'audio';
  title: string;
  /** Per-item captions, e.g. the character view name — falls back to `itemLabel`. */
  labels?: (string | null)[];
  itemLabel: (index: number, total: number) => string;
  /** Forwarded to `DevicePreview` — see its own prop for why a caller with
   * actions directly below the stage (e.g. `InlineImageResult`) needs this. */
  maxHeight?: number;
}) {
  const [selected, setSelected] = useState(0);
  const activeIndex = Math.min(selected, urls.length - 1);
  const activeUrl = urls[activeIndex];
  const activeAssetId = assetIds?.[activeIndex] ?? null;

  const refreshSrc = useCallback(async () => {
    if (activeAssetId) return refreshAssetUrl(activeAssetId);
    return activeUrl ?? null;
  }, [activeAssetId, activeUrl]);

  return (
    <div className="flex flex-col gap-3">
      {mediaType === 'audio' ? (
        <audio
          key={activeUrl}
          src={activeUrl}
          controls
          className="w-full rounded-[var(--radius-md)] border border-border p-4"
        />
      ) : (
        <DevicePreview
          key={activeUrl}
          src={activeUrl}
          title={title}
          mediaType={mediaType}
          refreshSrc={refreshSrc}
          maxHeight={maxHeight}
        />
      )}

      <ol className="flex flex-wrap gap-2">
        {urls.map((url, index) => {
          const caption = labels?.[index] || itemLabel(index + 1, urls.length);
          const active = index === activeIndex;
          return (
            <li key={`${url}-${index}`}>
              <button
                type="button"
                onClick={() => setSelected(index)}
                aria-current={active ? 'true' : undefined}
                aria-label={caption}
                className={cn(
                  'flex min-h-9 items-center gap-2 rounded-[var(--radius-sm)] border px-2.5 text-xs font-medium transition-colors',
                  'focus-visible:outline-2',
                  active
                    ? 'border-primary bg-primary/12 text-primary'
                    : 'border-border bg-surface-soft text-muted hover:text-text',
                )}
              >
                {mediaType === 'image' ? (
                  // eslint-disable-next-line @next/next/no-img-element -- small thumbnail of a signed object URL.
                  <img
                    src={url}
                    alt=""
                    className="size-6 shrink-0 rounded-[calc(var(--radius-sm)*0.6)] object-cover"
                  />
                ) : null}
                <span className="whitespace-nowrap">{caption}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
