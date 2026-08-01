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
  priority,
  sizes = '(max-width: 760px) 100vw, 33vw',
  className,
  children,
}: {
  src?: string | null;
  alt: string;
  aspect?: 'video' | 'square' | 'portrait';
  priority?: boolean;
  sizes?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const ratio =
    aspect === 'video' ? 'aspect-video' : aspect === 'square' ? 'aspect-square' : 'aspect-[3/4]';

  return (
    <div
      className={cn(
        'poster-scrim relative overflow-hidden rounded-[var(--radius-md)] bg-surface-soft',
        ratio,
        className,
      )}
    >
      {src ? (
        <Image
          src={src}
          alt={alt}
          fill
          sizes={sizes}
          priority={priority}
          className="object-cover"
        />
      ) : (
        <div className="absolute inset-0 grid place-items-center px-4 text-center text-xs text-muted">
          {alt}
        </div>
      )}
      {children}
    </div>
  );
}
