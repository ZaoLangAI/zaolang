import Image from 'next/image';

import { IconMic } from '@/components/ui/icons';

function VideoFirstFrame({ src }: { src: string }) {
  return (
    <video
      src={`${src}#t=0.1`}
      muted
      playsInline
      preload="metadata"
      className="size-full object-cover"
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        if (video.currentTime < 0.1) video.currentTime = 0.1;
      }}
    />
  );
}

/** Thumbnail for a moderation/report/appeal subject: video-first-frame,
 * audio icon, or a static image, all sharing one square footprint. */
export function SubjectThumb({
  url,
  mediaType,
}: {
  url?: string | null;
  mediaType?: string | null;
}) {
  return (
    <span className="relative size-9 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
      {mediaType === 'audio' ? (
        <span className="grid size-full place-items-center text-muted">
          <IconMic className="size-4" />
        </span>
      ) : url && mediaType === 'video' ? (
        <VideoFirstFrame src={url} />
      ) : url ? (
        <Image src={url} alt="" fill sizes="72px" className="object-cover" />
      ) : null}
    </span>
  );
}
