'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { Spinner } from '@/components/ui/spinner';

import { frameRectFor } from './compiler/camera';
import type { FrameState } from './compiler/compile';
import type { BlockingEdit } from './edits';
import type { BlockingEditor, EditorSelection, GizmoMode } from './engine/editor';
import type { BlockingPlayer, CastLabel, ViewMode } from './engine/player';
import type { AspectRatio, BlockingDocument } from './types';

/**
 * React host for the three.js player. The engine module (and three.js with
 * it) is loaded with a dynamic `import()` on mount, so only someone who
 * opens the 白膜 studio pays for it — same approach as
 * `features/canvas/panorama-viewer.tsx`.
 *
 * The canvas always fills the available area. In the director view the
 * delivered frame (the document's aspect) is outlined and everything around
 * it is dimmed — the author sees the frame as large as the area allows plus
 * what is just off it, and the exported clip is exactly the outlined rect.
 */
export function BlockingViewport({
  document,
  labels,
  aspect,
  view,
  onPlayer,
  editable,
  gizmoMode,
  onEdit,
  onSelect,
  onEditor,
  loadingLabel,
  errorLabel,
  children,
}: {
  document: BlockingDocument | null;
  labels: Record<string, CastLabel>;
  aspect: AspectRatio;
  view: ViewMode;
  onPlayer: (player: BlockingPlayer | null) => void;
  /** Drag editing is live only in the free view. */
  editable: boolean;
  gizmoMode: GizmoMode;
  onEdit: (edit: BlockingEdit) => void;
  onSelect: (selection: EditorSelection) => void;
  onEditor?: (editor: BlockingEditor | null) => void;
  loadingLabel: string;
  errorLabel: string;
  /** Overlays drawn over the viewport (empty state, streaming progress,
   * the edit toolbar). */
  children?: React.ReactNode;
}) {
  const areaRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const labelRef = useRef<HTMLDivElement | null>(null);
  const [player, setPlayer] = useState<BlockingPlayer | null>(null);
  const [editor, setEditor] = useState<BlockingEditor | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [size, setSize] = useState({ width: 0, height: 0 });

  const onPlayerRef = useRef(onPlayer);
  const handlersRef = useRef({ onEdit, onSelect, onEditor });
  useEffect(() => {
    onPlayerRef.current = onPlayer;
    handlersRef.current = { onEdit, onSelect, onEditor };
  }, [onPlayer, onEdit, onSelect, onEditor]);

  useEffect(() => {
    let cancelled = false;
    let instance: BlockingPlayer | null = null;
    let editorInstance: BlockingEditor | null = null;
    void Promise.all([import('./engine/player'), import('./engine/editor')])
      .then(([{ BlockingPlayer: Player }, { BlockingEditor: Editor }]) => {
        const canvas = canvasRef.current;
        if (cancelled || !canvas || !labelRef.current) return;
        instance = new Player({
          canvas,
          interactive: true,
          labelLayer: labelRef.current,
          pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        });
        editorInstance = new Editor(instance, canvas, {
          onEdit: (edit) => handlersRef.current.onEdit(edit),
          onSelect: (selection) => handlersRef.current.onSelect(selection),
        });
        setPlayer(instance);
        setEditor(editorInstance);
        onPlayerRef.current(instance);
        handlersRef.current.onEditor?.(editorInstance);
        setStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
      onPlayerRef.current(null);
      handlersRef.current.onEditor?.(null);
      editorInstance?.dispose();
      instance?.dispose();
    };
  }, []);

  // The canvas tracks the area; the frame rect is derived from it.
  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    // A ResizeObserver reports the initial size on `observe`, so no
    // synchronous first measure (and no setState inside the effect body).
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0)
        setSize({ width: Math.floor(width), height: Math.floor(height) });
    });
    observer.observe(area);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (player && size.width > 0) player.setSize(size.width, size.height);
  }, [player, size]);

  useEffect(() => {
    if (player && document) player.setDocument(document, labels);
  }, [player, document, labels]);

  useEffect(() => {
    player?.setView(view);
  }, [player, view]);

  useEffect(() => {
    editor?.setEnabled(editable && view === 'free');
  }, [editor, editable, view]);

  useEffect(() => {
    editor?.setMode(gizmoMode);
  }, [editor, gizmoMode]);

  const frame = size.width > 0 ? frameRectFor(size.width, size.height, aspect) : null;
  return (
    <div
      ref={areaRef}
      className="relative min-h-0 flex-1 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
    >
      <canvas ref={canvasRef} className="absolute inset-0 block size-full touch-none" />
      <div ref={labelRef} className="pointer-events-none absolute inset-0" aria-hidden />
      {view === 'director' && frame && document ? (
        // The delivered frame: outlined, with everything around it dimmed.
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-[2px] outline outline-2 outline-primary/80 shadow-[0_0_0_9999px_var(--overlay)]"
          style={{ left: frame.x, top: frame.y, width: frame.width, height: frame.height }}
        />
      ) : null}
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
