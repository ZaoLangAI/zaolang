'use client';

import Image from 'next/image';

import { isVideoPosterSrc } from '@/components/media/safe-media-playback';
import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { cn } from '@/lib/cn';

/**
 * Poster frame for a work.
 *
 * The design forbids placeholder art, so a missing cover renders as an honest
 * empty surface with the title rather than as fake imagery. Video covers show
 * the first decoded frame and stay still — a looping preview is not a poster.
 */
export function Poster({
  src,
  alt,
  aspect = 'video',
  ratio,
  priority,
  sizes = '(max-width: 760px) 100vw, 33vw',
  className,
  children,
  mediaType,
  lazy,
  onMediaSize,
}: {
  src?: string | null;
  alt: string;
  /** `fill` takes no preset ratio at all — the caller's `className` must supply a height instead. */
  aspect?: 'video' | 'square' | 'portrait' | 'fill';
  /** Width over height. Overrides `aspect`, for covers of any shape. */
  ratio?: number;
  priority?: boolean;
  sizes?: string;
  className?: string;
  children?: React.ReactNode;
  /** `'video'` (or a video URL) renders a first-frame still instead of `<Image>`. */
  mediaType?: 'image' | 'video' | 'audio' | null;
  /** Defer attaching a video `src` until the poster is near the viewport. */
  lazy?: boolean;
  /** Intrinsic pixel size once the image or first frame is known. */
  onMediaSize?: (width: number, height: number) => void;
}) {
  const preset =
    aspect === 'fill'
      ? null
      : aspect === 'video'
        ? 'aspect-video'
        : aspect === 'square'
          ? 'aspect-square'
          : 'aspect-[3/4]';
  const showFirstFrame = isVideoPosterSrc(src, mediaType);

  return (
    <div
      style={ratio ? { aspectRatio: ratio } : undefined}
      className={cn(
        'poster-scrim relative overflow-hidden rounded-[var(--radius-md)] bg-surface-soft',
        ratio ? null : preset,
        className,
      )}
    >
      {src ? (
        showFirstFrame ? (
          <VideoFirstFrame src={src} label={alt} lazy={lazy} onMediaSize={onMediaSize} />
        ) : (
          <Image
            src={src}
            alt={alt}
            fill
            sizes={sizes}
            priority={priority}
            className="object-cover"
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth > 0 && image.naturalHeight > 0) {
                onMediaSize?.(image.naturalWidth, image.naturalHeight);
              }
            }}
          />
        )
      ) : (
        <div className="absolute inset-0 grid place-items-center px-4 text-center text-xs text-muted">
          {alt}
        </div>
      )}
      {children}
    </div>
  );
}
