'use client';

import { useEffect, useRef, useState } from 'react';

import { decodeAudioBuffer } from './engine/audio-mixer';
import { computePeaks, ticksToSeconds } from './engine/waveform';

const THUMB_WIDTH = 64;
const THUMB_HEIGHT = 40;

// Module-scoped so every clip that shares an asset (a re-used video/audio
// upload cut into several timeline elements) reuses the same pooled
// `<video>` element and decoded frames/peaks instead of each clip refetching
// and reseeking independently.
const videoPool = new Map<string, HTMLVideoElement>();
const videoQueues = new Map<string, Promise<unknown>>();
const thumbCache = new Map<string, string>();

function withQueue<T>(key: string, task: () => Promise<T>): Promise<T> {
  const prior = videoQueues.get(key) ?? Promise.resolve();
  const next = prior.then(task, task);
  videoQueues.set(
    key,
    next.catch(() => undefined),
  );
  return next;
}

function waitFor(target: HTMLVideoElement, event: string): Promise<void> {
  return new Promise((resolve) => {
    const onEvent = () => {
      target.removeEventListener(event, onEvent);
      resolve();
    };
    target.addEventListener(event, onEvent);
  });
}

/**
 * Grabs a single downscaled JPEG frame near `timeSec` of `assetId`'s video,
 * cached by (asset, rounded time). A per-asset queue serializes seeks on the
 * one pooled `<video>` element — concurrent clips sharing an asset would
 * otherwise stomp on each other's `currentTime`.
 */
async function captureFrame(assetId: string, url: string, timeSec: number): Promise<string | null> {
  const cacheKey = `${assetId}:${timeSec.toFixed(2)}`;
  const cached = thumbCache.get(cacheKey);
  if (cached) return cached;

  return withQueue(assetId, async (): Promise<string | null> => {
    const filled = thumbCache.get(cacheKey);
    if (filled) return filled;

    let video = videoPool.get(assetId);
    if (!video) {
      video = document.createElement('video');
      video.crossOrigin = 'anonymous';
      video.muted = true;
      video.preload = 'metadata';
      video.src = url;
      videoPool.set(assetId, video);
    }
    if (video.readyState < 1) {
      await Promise.race([waitFor(video, 'loadedmetadata'), waitFor(video, 'error')]);
    }
    if (!Number.isFinite(video.duration) || video.duration <= 0) return null;

    const clamped = Math.min(Math.max(0, timeSec), Math.max(0, video.duration - 0.05));
    video.currentTime = clamped;
    await waitFor(video, 'seeked');

    const canvas = document.createElement('canvas');
    canvas.width = THUMB_WIDTH;
    canvas.height = THUMB_HEIGHT;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    try {
      ctx.drawImage(video, 0, 0, THUMB_WIDTH, THUMB_HEIGHT);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
      thumbCache.set(cacheKey, dataUrl);
      return dataUrl;
    } catch {
      // Cross-origin taint or a mid-seek decode error — degrade to no
      // thumbnails for this asset rather than throwing inside a render loop.
      return null;
    }
  });
}

/** Tiled frame thumbnails behind a video clip's timeline block, sampled evenly across its trimmed-in source range. */
export function ClipThumbnails({
  assetId,
  url,
  sourceInTicks,
  sourceOutTicks,
  widthPx,
}: {
  assetId: string;
  url: string;
  sourceInTicks: number;
  sourceOutTicks: number;
  widthPx: number;
}) {
  const [thumbs, setThumbs] = useState<string[]>([]);
  const count = Math.max(1, Math.min(8, Math.round(widthPx / 56)));

  useEffect(() => {
    let cancelled = false;
    const startSec = ticksToSeconds(sourceInTicks);
    const endSec = ticksToSeconds(sourceOutTicks);
    const span = Math.max(0.001, endSec - startSec);

    void (async () => {
      const collected: string[] = [];
      for (let i = 0; i < count; i++) {
        if (cancelled) return;
        const timeSec = startSec + ((i + 0.5) / count) * span;
        const frame = await captureFrame(assetId, url, timeSec);
        if (cancelled) return;
        if (frame) {
          collected.push(frame);
          setThumbs([...collected]);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [assetId, url, sourceInTicks, sourceOutTicks, count]);

  if (thumbs.length === 0) return null;
  return (
    <div
      className="pointer-events-none absolute inset-0 flex overflow-hidden opacity-60"
      aria-hidden
    >
      {thumbs.map((src, index) => (
        // eslint-disable-next-line @next/next/no-img-element -- tiny cached data URL, not a real <Image>
        <img key={index} src={src} alt="" className="h-full min-w-0 flex-1 object-cover" />
      ))}
    </div>
  );
}

/** Peak-amplitude waveform bars behind an audio clip's timeline block. */
export function ClipWaveform({
  assetId,
  url,
  sourceInTicks,
  sourceOutTicks,
  widthPx,
  heightPx = 32,
}: {
  assetId: string;
  url: string;
  sourceInTicks: number;
  sourceOutTicks: number;
  widthPx: number;
  heightPx?: number;
}) {
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bucketCount = Math.max(8, Math.min(200, Math.round(widthPx / 3)));

  useEffect(() => {
    let cancelled = false;
    decodeAudioBuffer(assetId, url).then((buffer) => {
      if (cancelled || !buffer) return;
      const startSec = ticksToSeconds(sourceInTicks);
      const endSec = ticksToSeconds(sourceOutTicks);
      setPeaks(computePeaks(buffer, bucketCount, startSec, endSec));
    });
    return () => {
      cancelled = true;
    };
  }, [assetId, url, sourceInTicks, sourceOutTicks, bucketCount]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !peaks) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(widthPx * dpr));
    canvas.height = Math.max(1, Math.round(heightPx * dpr));
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, widthPx, heightPx);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
    const barWidth = widthPx / peaks.length;
    peaks.forEach((peak, index) => {
      const barHeight = Math.max(1, peak * heightPx);
      ctx.fillRect(
        index * barWidth,
        (heightPx - barHeight) / 2,
        Math.max(1, barWidth - 1),
        barHeight,
      );
    });
  }, [peaks, widthPx, heightPx]);

  if (!peaks) return null;
  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 size-full opacity-80"
      style={{ width: widthPx, height: heightPx }}
    />
  );
}
