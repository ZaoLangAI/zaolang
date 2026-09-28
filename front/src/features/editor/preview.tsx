'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  IconFullscreen,
  IconPause,
  IconPlay,
  IconSkipBack,
  IconSkipForward,
  IconStepBack,
  IconStepForward,
} from '@/components/ui/icons';

import type { EditorActions } from './actions';
import { AudioMixer } from './engine/audio-mixer';
import { composeFrame, MediaPool } from './engine/compositor';
import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type ResolvedAsset,
  type TimelineElement,
} from './engine/ports';
import { MaskOverlay } from './mask-overlay';
import { useEditorUi } from './store';
import { canvasFps, formatTimecode } from './timeline/geometry';
import { TransformGizmo } from './transform-gizmo';

function ToolbarButton({
  label,
  shortcut,
  onClick,
  disabled,
  children,
}: {
  label: string;
  shortcut?: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const title = shortcut ? `${label} (${shortcut})` : label;
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex size-7 items-center justify-center rounded-[var(--radius-sm)] text-text hover:bg-surface-soft disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/**
 * Canvas-composited preview: resolves the active clip/caption/overlay at the
 * playhead via `compositor.ts` and draws it, instead of just playing the
 * original source file. Edits (trim/split/caption/volume/speed) are visible
 * immediately because this shares the same frame-resolution logic the
 * export runner uses. Below it, an OpenCut-style transport bar; on top of
 * it, the transform gizmo / mask box for the selected element.
 */
export function Preview({
  document,
  assets,
  durationTicks,
  title,
  selected,
  disabled,
  actions,
  onApply,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  title: string;
  selected?: TimelineElement | undefined;
  disabled?: boolean;
  actions: EditorActions;
  onApply?: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const poolRef = useRef<MediaPool | null>(null);
  const audioMixerRef = useRef<AudioMixer | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef<number | null>(null);
  // One frame in flight at a time — a slow `composeFrame` (seek + decode)
  // must not pile up behind a fast playhead; the newest requested tick wins.
  const renderingRef = useRef(false);
  const pendingTickRef = useRef<number | null>(null);
  const renderRef = useRef<((tick: number) => void) | null>(null);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const playing = useEditorUi((state) => state.playing);
  const setPlaying = useEditorUi((state) => state.setPlaying);
  const snappingEnabled = useEditorUi((state) => state.snappingEnabled);
  const [fullscreen, setFullscreen] = useState(false);

  const empty = document.tracks.every((track) => track.elements.length === 0);
  const fps = canvasFps(document.canvas);
  const assetUrls = useMemo(
    () => new Map(assets.map((asset) => [asset.asset_id, asset.url])),
    [assets],
  );

  useEffect(() => {
    poolRef.current = new MediaPool();
    audioMixerRef.current = new AudioMixer();
    return () => {
      poolRef.current?.dispose();
      poolRef.current = null;
      audioMixerRef.current?.dispose();
      audioMixerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const pool = poolRef.current;
    if (!canvas || !pool || empty) return;
    if (canvas.width !== document.canvas.width) canvas.width = document.canvas.width;
    if (canvas.height !== document.canvas.height) canvas.height = document.canvas.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const render = (tick: number) => {
      renderingRef.current = true;
      void composeFrame(ctx, canvas.width, canvas.height, document, tick, assets, pool, { playing })
        .catch((error: unknown) => {
          // A failed frame is just a skipped frame — the next tick redraws.
          console.error('[editor] preview frame failed', error);
        })
        .finally(() => {
          renderingRef.current = false;
          const pending = pendingTickRef.current;
          pendingTickRef.current = null;
          // Drain through the ref, not this closure: the inputs (document,
          // `playing`, ...) may have changed while this frame was in flight,
          // and the pending tick must be drawn with the current ones — e.g.
          // the pause that arrived mid-frame has to actually stop the videos.
          if (pending != null) renderRef.current?.(pending);
        });
    };
    renderRef.current = render;
    if (renderingRef.current) pendingTickRef.current = playheadTicks;
    else render(playheadTicks);
    // Audio only actually sounds during playback — scrubbing while paused
    // stays silent, matching how a paused video element behaves elsewhere.
    if (playing) {
      audioMixerRef.current?.sync(document, playheadTicks, assetUrls);
    } else {
      audioMixerRef.current?.stopAll();
    }
    return () => {
      if (renderRef.current === render) renderRef.current = null;
    };
  }, [document, playheadTicks, assets, assetUrls, empty, playing]);

  // Browsers only let an AudioContext resume after a user gesture; the
  // play toggle always comes from one (button or key), and sticky activation
  // keeps this effect-time call inside that allowance.
  useEffect(() => {
    if (playing) void audioMixerRef.current?.resume();
  }, [playing]);

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
      // Read the live value from the store — the closure's `playheadTicks`
      // is frozen at the render this effect was armed on.
      const current = useEditorUi.getState().playheadTicks;
      const next = current + deltaSeconds * TICKS_PER_SECOND;
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
  }, [playing, durationTicks, setPlayhead, setPlaying]);

  useEffect(() => {
    const onChange = () => setFullscreen(!!window.document.fullscreenElement);
    window.document.addEventListener('fullscreenchange', onChange);
    return () => window.document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = () => {
    const stage = stageRef.current;
    if (!stage) return;
    if (window.document.fullscreenElement) void window.document.exitFullscreen();
    else void stage.requestFullscreen?.();
  };

  if (empty) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center rounded-[var(--radius-md)] border border-border bg-surface-soft text-sm text-muted">
        {title}
      </div>
    );
  }

  const gizmoTarget =
    selected && (selected.type === 'clip' || selected.type === 'sticker') ? selected : undefined;
  const maskOverlayTarget = gizmoTarget && gizmoTarget.mask ? gizmoTarget : undefined;
  const timecode = `${formatTimecode(playheadTicks, fps)} / ${formatTimecode(durationTicks, fps)}`;

  return (
    <div ref={stageRef} className="flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        <div
          data-mask-surface
          className="relative h-auto w-auto max-h-full max-w-full"
          style={{ aspectRatio: `${document.canvas.width} / ${document.canvas.height}` }}
        >
          <canvas
            ref={canvasRef}
            className="block h-full w-full rounded-[var(--radius-md)] border border-border bg-track object-contain"
          />
          {gizmoTarget && onApply ? (
            <TransformGizmo
              key={gizmoTarget.id}
              element={gizmoTarget}
              playheadTicks={playheadTicks}
              disabled={Boolean(disabled)}
              snappingEnabled={snappingEnabled}
              onCommit={onApply}
            />
          ) : null}
          {maskOverlayTarget && onApply ? (
            <MaskOverlay
              key={`mask-${maskOverlayTarget.id}`}
              mask={maskOverlayTarget.mask!}
              elementId={maskOverlayTarget.id}
              disabled={Boolean(disabled)}
              onCommit={onApply}
            />
          ) : null}
        </div>
      </div>
      <div className="flex h-10 shrink-0 items-center gap-0.5 border-t border-border px-2">
        <ToolbarButton label={t('goToStart')} shortcut="Home" onClick={actions.goToStart}>
          <IconSkipBack />
        </ToolbarButton>
        <ToolbarButton label={t('stepBack')} shortcut="←" onClick={() => actions.stepFrames(-1)}>
          <IconStepBack />
        </ToolbarButton>
        <ToolbarButton
          label={playing ? t('pause') : t('play')}
          shortcut="Space"
          onClick={actions.togglePlay}
        >
          {playing ? <IconPause /> : <IconPlay />}
        </ToolbarButton>
        <ToolbarButton label={t('stepForward')} shortcut="→" onClick={() => actions.stepFrames(1)}>
          <IconStepForward />
        </ToolbarButton>
        <ToolbarButton label={t('goToEnd')} shortcut="End" onClick={actions.goToEnd}>
          <IconSkipForward />
        </ToolbarButton>
        <span className="ml-2 font-mono text-[11px] tabular-nums text-muted" aria-live="off">
          {timecode}
        </span>
        <span className="ml-auto text-[10px] text-muted">{t('previewScrubMuted')}</span>
        <ToolbarButton
          label={fullscreen ? t('exitFullscreen') : t('fullscreen')}
          onClick={toggleFullscreen}
        >
          <IconFullscreen />
        </ToolbarButton>
      </div>
    </div>
  );
}
