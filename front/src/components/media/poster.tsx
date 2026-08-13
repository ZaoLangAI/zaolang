import Image from 'next/image';

import { cn } from '@/lib/cn';

/**
 * Poster frame for a work.
 *
 * The design forbids placeholder art, so a missing cover renders as an honest
 * empty surface with the title rather than as fake imagery.
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
  /** `'video'` renders `src` as a looping, muted `<video>` instead of an
   * `<Image>` — omit (or any other value) to keep the default image path. */
  mediaType?: 'image' | 'video' | 'audio' | null;
}) {
  const preset =
    aspect === 'fill'
      ? null
      : aspect === 'video'
        ? 'aspect-video'
        : aspect === 'square'
          ? 'aspect-square'
          : 'aspect-[3/4]';

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
        mediaType === 'video' ? (
          <video
            src={src}
            aria-label={alt}
            muted
            loop
            playsInline
            autoPlay
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <Image
            src={src}
            alt={alt}
            fill
            sizes={sizes}
            priority={priority}
            className="object-cover"
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
