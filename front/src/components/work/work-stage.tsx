import { DevicePreview } from '@/components/media/device-preview';
import { Poster } from '@/components/media/poster';
import { VideoPlayer } from '@/components/media/video-player';
import type { WorkDetail } from '@/lib/api/types';
import { cn } from '@/lib/cn';

/**
 * The large media area on discover and the work page.
 *
 * Video gets the player; stills get a plain poster, because a control bar over
 * an image is a lie about what the medium is.
 */
export function WorkStage({
  work,
  lazyMedia = false,
  devicePreview = false,
  fill = false,
  className,
}: {
  work: WorkDetail;
  /** Discover hero: poster-first, attach video src on play. */
  lazyMedia?: boolean;
  /**
   * Offers the phone frames. The detail page wants it; the discover hero does
   * not, because a feed is for deciding what to watch, not how it crops.
   */
  devicePreview?: boolean;
  /**
   * Fills the caller's box height (via `className`) instead of keeping the
   * media's own aspect ratio — the hero carousel needs the video pane to
   * match the info pane's height exactly, not just look roughly the same.
   */
  fill?: boolean;
  className?: string;
}) {
  const version = work.current_version;
  const isVideo = (work.media_type ?? version?.media_type) === 'video';

  if (isVideo && devicePreview) {
    return (
      <DevicePreview
        src={version?.media_url}
        poster={version?.cover_url ?? work.cover_url}
        title={work.title}
        edgeToEdge
      />
    );
  }

  if (isVideo) {
    return (
      <VideoPlayer
        src={version?.media_url}
        poster={version?.cover_url ?? work.cover_url}
        title={work.title}
        className={cn('rounded-[var(--radius-lg)]', className)}
        lazyMedia={lazyMedia}
        aspectRatio={fill ? null : undefined}
        objectFit={fill ? 'cover' : undefined}
      />
    );
  }

  return (
    <Poster
      src={version?.media_url ?? version?.cover_url ?? work.cover_url}
      alt={work.title}
      aspect={fill ? 'fill' : 'video'}
      className={cn('rounded-[var(--radius-lg)] border border-border', className)}
      priority
    />
  );
}
