'use client';

import { Poster } from '@/components/media/poster';
import { IconPlay } from '@/components/ui/icons';
import type { Draft } from '@/lib/api/types';

/**
 * Draft card media: stills stay on `Poster`, video shows the first frame
 * without autoplay, audio keeps the honest empty surface.
 */
export function DraftPoster({
  draft,
  alt,
  className,
  children,
}: {
  draft: Draft;
  alt: string;
  className?: string;
  children?: React.ReactNode;
}) {
  if (draft.output_media_type === 'video' && draft.output_url) {
    return (
      <Poster
        src={draft.output_url}
        alt={alt}
        aspect="video"
        mediaType="video"
        className={className}
      >
        <span className="pointer-events-none absolute bottom-2 right-2 grid size-7 place-items-center rounded-full bg-black/70 text-white">
          <IconPlay className="size-3.5" />
        </span>
        {children}
      </Poster>
    );
  }

  return (
    <Poster
      src={draft.output_media_type === 'audio' ? null : draft.output_url}
      alt={alt}
      aspect="video"
      className={className}
    >
      {children}
    </Poster>
  );
}
