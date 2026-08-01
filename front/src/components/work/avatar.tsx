import Image from 'next/image';

import { cn } from '@/lib/cn';

const sizes = { sm: 'size-8 text-xs', md: 'size-10 text-sm', lg: 'size-14 text-lg' } as const;

/**
 * Falls back to the first character rather than a generic silhouette, so a
 * lineage strip of avatars stays distinguishable when covers are missing.
 */
export function Avatar({
  src,
  name,
  size = 'md',
  className,
}: {
  src?: string | null;
  name: string;
  size?: keyof typeof sizes;
  className?: string;
}) {
  const pixels = size === 'sm' ? 32 : size === 'md' ? 40 : 56;

  return (
    <span
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-surface-soft font-medium text-muted',
        sizes[size],
        className,
      )}
    >
      {src ? (
        <Image src={src} alt="" width={pixels} height={pixels} className="size-full object-cover" />
      ) : (
        <span aria-hidden="true">{name.slice(0, 1)}</span>
      )}
    </span>
  );
}
