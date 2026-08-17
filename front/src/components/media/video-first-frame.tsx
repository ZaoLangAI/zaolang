'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

/** Past the black frame some encoders leave at t=0, still inside the first GOP. */
export const FIRST_FRAME_SECONDS = 0.1;

export function videoFirstFrameSrc(src: string): string {
  // Signed MinIO URLs plus a `#t=` fragment make Chromium report
  // MEDIA_ELEMENT_ERROR: Format error. Seek on `loadedmetadata` instead.
  const hash = src.indexOf('#');
  return hash >= 0 ? src.slice(0, hash) : src;
}

export function seekVideoToFirstFrame(video: HTMLVideoElement) {
  if (video.paused && video.currentTime < FIRST_FRAME_SECONDS) {
    video.currentTime = FIRST_FRAME_SECONDS;
  }
}

/**
 * Still of a video's first decoded frame. Does not play or loop — cards and
 * idle players use this instead of feeding an mp4 to `next/image` or `poster`.
 */
export function VideoFirstFrame({
  src,
  label,
  className,
  lazy = false,
  onClick,
  onMediaSize,
}: {
  src: string;
  label?: string;
  className?: string;
  /** Wait until the element is near the viewport before attaching `src`. */
  lazy?: boolean;
  onClick?: () => void;
  onMediaSize?: (width: number, height: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // Only tracks the observer's "became visible" signal — a non-`lazy` element
  // never needs it set, so `ready` below is derived rather than seeded from
  // `lazy` and then reconciled again inside the effect.
  const [visible, setVisible] = useState(false);
  const ready = !lazy || visible;

  useEffect(() => {
    if (!lazy) return;
    const node = videoRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        setVisible(true);
      },
      { rootMargin: '80px', threshold: 0.01 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [src, lazy]);

  return (
    <video
      ref={videoRef}
      src={ready ? videoFirstFrameSrc(src) : undefined}
      muted
      playsInline
      preload="metadata"
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn('absolute inset-0 size-full object-cover', className)}
      onClick={onClick}
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        seekVideoToFirstFrame(video);
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          onMediaSize?.(video.videoWidth, video.videoHeight);
        }
      }}
    />
  );
}
