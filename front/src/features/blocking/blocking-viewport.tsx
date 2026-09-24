'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { Spinner } from '@/components/ui/spinner';

import { ASPECT_WIDTH_OVER_HEIGHT } from './compiler/camera';
import type { FrameState } from './compiler/compile';
import type { BlockingPlayer, CastLabel, ViewMode } from './engine/player';
import type { AspectRatio, BlockingDocument } from './types';

/**
 * React host for the three.js player. The engine module (and three.js with
 * it) is loaded with a dynamic `import()` on mount, so only someone who
 * opens the 白膜 studio pays for it — same approach as
 * `features/canvas/panorama-viewer.tsx`.
 *
 * The canvas is letterboxed to the document's aspect ratio so what the
 * author frames here is exactly what the exported reference clip shows.
 */
export function BlockingViewport({
  document,
  labels,
  aspect,
  view,
  onPlayer,
  loadingLabel,
  errorLabel,
  children,
}: {
  document: BlockingDocument | null;
  labels: Record<string, CastLabel>;
  aspect: AspectRatio;
  view: ViewMode;
  onPlayer: (player: BlockingPlayer | null) => void;
  loadingLabel: string;
  errorLabel: string;
  /** Overlays drawn over the frame (empty state, streaming progress). */
  children?: React.ReactNode;
}) {
  const areaRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const labelRef = useRef<HTMLDivElement | null>(null);
  const [player, setPlayer] = useState<BlockingPlayer | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [frame, setFrame] = useState({ width: 0, height: 0 });

  const onPlayerRef = useRef(onPlayer);
  useEffect(() => {
    onPlayerRef.current = onPlayer;
  }, [onPlayer]);

  useEffect(() => {
    let cancelled = false;
    let instance: BlockingPlayer | null = null;
    void import('./engine/player')
      .then(({ BlockingPlayer: Player }) => {
        if (cancelled || !canvasRef.current || !labelRef.current) return;
        instance = new Player({
          canvas: canvasRef.current,
          interactive: true,
          labelLayer: labelRef.current,
          pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        });
        setPlayer(instance);
        onPlayerRef.current(instance);
        setStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
      onPlayerRef.current(null);
      instance?.dispose();
    };
  }, []);

  // Fit the frame inside the available area at the document's aspect.
  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const ratio = ASPECT_WIDTH_OVER_HEIGHT[aspect];
    const fit = () => {
      const { width, height } = area.getBoundingClientRect();
      if (width <= 0 || height <= 0) return;
      const fitted = width / height > ratio
        ? { width: height * ratio, height }
        : { width, height: width / ratio };
      setFrame({ width: Math.floor(fitted.width), height: Math.floor(fitted.height) });
    };
    // A ResizeObserver reports the initial size on `observe`, so no
    // synchronous first `fit()` (and no setState inside the effect body).
    const observer = new ResizeObserver(fit);
    observer.observe(area);
    return () => observer.disconnect();
  }, [aspect]);

  useEffect(() => {
    if (player && frame.width > 0) player.setSize(frame.width, frame.height);
  }, [player, frame]);

  useEffect(() => {
    if (player && document) player.setDocument(document, labels);
  }, [player, document, labels]);

  useEffect(() => {
    player?.setView(view);
  }, [player, view]);

  return (
    <div ref={areaRef} className="relative flex min-h-0 flex-1 items-center justify-center">
      <div
        className="relative overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft shadow-card"
        style={{ width: frame.width || undefined, height: frame.height || undefined }}
      >
        <canvas ref={canvasRef} className="block size-full touch-none" />
        <div ref={labelRef} className="pointer-events-none absolute inset-0" aria-hidden />
        {status === 'loading' ? (
          <div className="absolute inset-0 grid place-items-center">
            <Spinner label={loadingLabel} />
          </div>
        ) : null}
        {status === 'error' ? (
          <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-danger">
            {errorLabel}
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}

/** Re-renders the caller on every player tick — keep it to small leaf
 * components (transport, scrubber), not the whole studio. */
export function usePlayerClock(player: BlockingPlayer | null): {
  time: number;
  playing: boolean;
  frame: FrameState | null;
} {
  const snapshot = useSyncExternalStore(
    (notify) => (player ? player.subscribe(notify) : () => undefined),
    () => (player ? `${player.time}|${player.playing}` : '0|false'),
    () => '0|false',
  );
  const [time, playing] = snapshot.split('|');
  return {
    time: Number(time),
    playing: playing === 'true',
    frame: player?.lastFrame ?? null,
  };
}
