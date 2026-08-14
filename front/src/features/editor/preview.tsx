'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';

import { composeFrame, MediaPool } from './engine/compositor';
import { TICKS_PER_SECOND, type CanonicalDocument, type ResolvedAsset } from './engine/ports';
import { useEditorUi } from './store';

/**
 * Canvas-composited preview: resolves the active clip/caption/overlay at the
 * playhead via `compositor.ts` and draws it, instead of just playing the
 * original source file. Edits (trim/split/caption/volume/speed) are visible
 * immediately because this shares the same frame-resolution logic the
 * export runner uses.
 */
export function Preview({
  document,
  assets,
  durationTicks,
  title,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  title: string;
}) {
  const t = useTranslations('editor');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const poolRef = useRef<MediaPool | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef<number | null>(null);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const [playing, setPlaying] = useState(false);

  const empty = document.tracks.every((track) => track.elements.length === 0);

  useEffect(() => {
    poolRef.current = new MediaPool();
    return () => {
      poolRef.current?.dispose();
      poolRef.current = null;
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const pool = poolRef.current;
    if (!canvas || !pool || empty) return;
    let cancelled = false;
    canvas.width = document.canvas.width;
    canvas.height = document.canvas.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    void composeFrame(ctx, canvas.width, canvas.height, document, playheadTicks, assets, pool).then(
      () => {
        if (cancelled) return;
      },
    );
    return () => {
      cancelled = true;
    };
  }, [document, playheadTicks, assets, empty]);

  useEffect(() => {
    if (!playing) {
      lastFrameAtRef.current = null;
      return;
    }
    const span = Math.max(durationTicks, TICKS_PER_SECOND);
    const step = (now: number) => {
      if (lastFrameAtRef.current == null) lastFrameAtRef.current = now;
      const deltaSeconds = (now - lastFrameAtRef.current) / 1000;
      lastFrameAtRef.current = now;
      const next = playheadTicks + deltaSeconds * TICKS_PER_SECOND;
      if (next >= span) {
        setPlayhead(0);
        setPlaying(false);
        return;
      }
      setPlayhead(Math.round(next));
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
    // Re-armed only by the play/pause toggle; playheadTicks updates inside the loop itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, durationTicks]);

  if (empty) {
    return (
      <div className="grid aspect-video place-items-center rounded-[var(--radius-md)] border border-border bg-surface-soft text-sm text-muted">
        {title}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <canvas
        ref={canvasRef}
        className="w-full rounded-[var(--radius-md)] border border-border bg-black"
        style={{ aspectRatio: `${document.canvas.width} / ${document.canvas.height}` }}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => setPlaying((value) => !value)}>
          {playing ? t('pause') : t('play')}
        </Button>
        <p className="text-xs text-muted">{t('previewMuted')}</p>
      </div>
    </div>
  );
}
