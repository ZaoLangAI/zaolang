import { Poster } from '@/components/media/poster';
import { VideoPlayer } from '@/components/media/video-player';
import type { WorkDetail } from '@/lib/api/types';

/**
 * The large media area on discover and the work page.
 *
 * Video gets the player; stills get a plain poster, because a control bar over
 * an image is a lie about what the medium is.
 */
export function WorkStage({
  work,
  lazyMedia = false,
}: {
  work: WorkDetail;
  /** Discover hero: poster-first, attach video src on play. */
  lazyMedia?: boolean;
}) {
  const version = work.current_version;
  const isVideo = (work.media_type ?? version?.media_type) === 'video';

  if (isVideo) {
    return (
      <VideoPlayer
        src={version?.media_url}
        poster={version?.cover_url ?? work.cover_url}
        title={work.title}
        className="rounded-[var(--radius-lg)]"
        lazyMedia={lazyMedia}
      />
    );
  }

  return (
    <Poster
      src={version?.media_url ?? version?.cover_url ?? work.cover_url}
      alt={work.title}
      aspect="video"
      className="rounded-[var(--radius-lg)] border border-border"
      priority
    />
  );
}
