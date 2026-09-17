'use client';

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react';

import type { Viewer } from '@photo-sphere-viewer/core';

/**
 * A 360° panorama surface, used by the director to stand inside a scene.
 *
 * `@photo-sphere-viewer/core` depends on three.js — several hundred kilobytes —
 * so the module is loaded with a dynamic `import()` inside the effect. Only
 * someone who actually opens the director pays for it. The `Viewer` type above
 * is an `import type`, which TypeScript erases entirely, so naming the real
 * type here costs nothing at runtime and keeps the code-split intact.
 */

/** The class in the `.psv-canvas` element the library renders into. */
const PSV_CANVAS = '.psv-canvas';

const RADIANS_TO_DEGREES = 180 / Math.PI;

export interface PanoramaHandle {
  /** Current camera orientation, in degrees. */
  readPosition: () => { yaw: number; pitch: number; fov: number } | null;
  /** The rendered frame, as a canvas element that can be composited onto. */
  captureCanvas: () => HTMLCanvasElement | null;
}

type ViewerStatus = 'loading' | 'ready' | 'error';

/**
 * Tear down a viewer and hand its WebGL context back to the browser.
 *
 * A browser allows only a small number of live WebGL contexts, and `destroy()`
 * alone does not always release one promptly — the context lingers with the
 * garbage-collected renderer. Open and close the director a handful of times
 * and the oldest contexts get force-killed, so the panorama stops drawing.
 * Asking for `WEBGL_lose_context` first and calling it after `destroy()` makes
 * the release immediate and deterministic.
 *
 * The extension lookup has to happen *before* `destroy()`, because by then the
 * canvas is gone from the DOM.
 */
function disposeViewer(instance: Viewer): void {
  const lose = instance.container
    .querySelector<HTMLCanvasElement>(PSV_CANVAS)
    ?.getContext('webgl2')
    ?.getExtension('WEBGL_lose_context');
  try {
    instance.destroy();
  } finally {
    lose?.loseContext();
  }
}

export function PanoramaViewer({
  src,
  handleRef,
  onReady,
}: {
  src: string;
  handleRef?: Ref<PanoramaHandle>;
  onReady?: (ready: boolean) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const [status, setStatus] = useState<ViewerStatus>('loading');

  // Held in a ref, and deliberately not an effect dependency. Building a
  // viewer means compiling shaders and decoding a multi-megabyte equirect;
  // if a caller passed an inline arrow here, depending on it directly would
  // destroy and rebuild all of that on every render of the parent.
  const onReadyRef = useRef(onReady);
  // Assigned in an effect, not during render: React reserves render for pure
  // computation, and `react-hooks/refs` enforces it. Declared above the viewer
  // effect so it is the first to run on mount.
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  const report = useCallback((next: ViewerStatus) => {
    setStatus(next);
    onReadyRef.current?.(next === 'ready');
  }, []);

  useImperativeHandle(
    handleRef,
    () => ({
      readPosition: () => {
        const viewer = viewerRef.current;
        if (!viewer) return null;
        const { yaw, pitch } = viewer.getPosition();
        if (typeof yaw !== 'number' || typeof pitch !== 'number') return null;
        // The library works in radians. Degrees is what a person reads, and
        // what the framing sentence in `director-capture.ts` is written in.
        return {
          yaw: Math.round(yaw * RADIANS_TO_DEGREES),
          pitch: Math.round(pitch * RADIANS_TO_DEGREES),
          fov: Math.round(viewer.getZoomLevel()),
        };
      },
      captureCanvas: () =>
        containerRef.current?.querySelector<HTMLCanvasElement>(PSV_CANVAS) ?? null,
    }),
    [],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let cancelled = false;
    let instance: Viewer | null = null;

    report('loading');

    void (async () => {
      try {
        const [{ Viewer: ViewerClass }] = await Promise.all([
          import('@photo-sphere-viewer/core'),
          import('@photo-sphere-viewer/core/index.css'),
        ]);
        // The effect was cleaned up while the chunk was in flight. Nothing has
        // been constructed yet, so there is nothing to dispose — just stop.
        if (cancelled) return;

        instance = new ViewerClass({
          container,
          panorama: src,
          navbar: false,
          mousewheel: true,
          mousemove: true,
          // One finger drags the view. Two-finger panning would fight the
          // canvas' own pinch-zoom on touch devices.
          touchmoveTwoFingers: false,
          moveInertia: false,
          defaultZoomLvl: 50,
          minFov: 25,
          maxFov: 110,
          // Without this the drawing buffer is cleared as soon as the frame is
          // presented, and `captureCanvas` reads back a fully transparent
          // image — every director capture would come out blank.
          rendererParameters: { preserveDrawingBuffer: true },
        });
        viewerRef.current = instance;

        instance.addEventListener('ready', () => {
          if (!cancelled) report('ready');
        });
        // A panorama that will not decode or project is not a viewer failure —
        // it is a bad image. Report it so the flat fallback below takes over.
        instance.addEventListener('panorama-error', () => {
          if (!cancelled) report('error');
        });
      } catch {
        if (!cancelled) report('error');
      }
    })();

    return () => {
      cancelled = true;
      viewerRef.current = null;
      if (instance) disposeViewer(instance);
      instance = null;
    };
  }, [report, src]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {status === 'error' ? (
        // Show the picture flat rather than an empty box: a panorama that will
        // not project is still the image the person asked to look at.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          draggable={false}
          className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain"
        />
      ) : null}
      <div
        ref={containerRef}
        data-testid="panorama-surface"
        className="absolute inset-0 transition-opacity duration-200"
        style={{ opacity: status === 'ready' ? 1 : 0 }}
      />
    </div>
  );
}
