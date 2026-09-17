import Image from 'next/image';

import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { IconMic } from '@/components/ui/icons';

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
