'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { composeFrame, MediaPool } from './engine/compositor';
import type { PrecheckSample } from './engine/export-precheck';
import { TICKS_PER_SECOND, type CanonicalDocument, type ResolvedAsset } from './engine/ports';

/** `00:03.2` style timecode — mirrors `timeline.tsx`'s `formatTimecode`, kept
 * local rather than shared since it's a one-line pure function and the
 * "don't touch shared UI" boundary only cares about cross-cutting imports. */
function formatTimecode(ticks: number): string {
  const totalDeciseconds = Math.round((Math.max(0, ticks) / TICKS_PER_SECOND) * 10);
  const minutes = Math.floor(totalDeciseconds / 600);
  const seconds = Math.floor((totalDeciseconds % 600) / 10);
  const deci = totalDeciseconds % 10;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${deci}`;
}

/**
 * Renders one small offscreen thumbnail per sampled tick through the exact
 * same `composeFrame` pipeline the live preview and export runner use, so
 * "what you're about to export" is shown before paying for a full encode —
 * not a structural guess, an actual rendered frame.
 */
export function ExportPrecheckPanel({
  document,
  assets,
  samples,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  samples: PrecheckSample[];
}) {
  const t = useTranslations('editor');
  const [thumbs, setThumbs] = useState<Map<number, string | null>>(new Map());

  useEffect(() => {
    let cancelled = false;
    const pool = new MediaPool();
    const canvas = window.document.createElement('canvas');
    canvas.width = document.canvas.width;
    canvas.height = document.canvas.height;
    const ctx = canvas.getContext('2d');

    void (async () => {
      if (!ctx) return;
      for (const sample of samples) {
        if (cancelled) return;
        try {
          await composeFrame(
            ctx,
            canvas.width,
            canvas.height,
            document,
            sample.atTicks,
            assets,
            pool,
          );
          const src = canvas.toDataURL('image/jpeg', 0.6);
          if (!cancelled) setThumbs((prev) => new Map(prev).set(sample.atTicks, src));
        } catch {
          // A single tainted/undecodable frame shouldn't blank the whole strip.
          if (!cancelled) setThumbs((prev) => new Map(prev).set(sample.atTicks, null));
        }
      }
    })();

    return () => {
      cancelled = true;
      pool.dispose();
    };
  }, [document, assets, samples]);

  return (
    <div className="flex gap-1.5 overflow-x-auto">
      {samples.map((sample) => {
        const thumb = thumbs.get(sample.atTicks);
        return (
          <div key={sample.atTicks} className="flex shrink-0 flex-col items-center gap-0.5">
            <div
              className="flex h-14 w-9 items-center justify-center overflow-hidden rounded-[var(--radius-sm)] border border-border bg-track"
              aria-hidden={thumb === undefined}
            >
              {thumb ? (
                // eslint-disable-next-line @next/next/no-img-element -- tiny cached data URL, not a real <Image>
                <img src={thumb} alt="" className="size-full object-cover" />
              ) : thumb === null ? (
                <span className="text-[9px] text-muted">{t('exportPrecheckThumbFailed')}</span>
              ) : null}
            </div>
            <span className="font-mono text-[9px] text-muted">
              {formatTimecode(sample.atTicks)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
