export type StudioPrefetchMode = 'video_creation' | 'audio_generation' | 'music_generation';

/**
 * Warms the `/create/new` studio chunk that a create-mode card will open.
 *
 * The dynamic import paths must stay identical to
 * `components/studio/create-studio.tsx` so the hover prefetch and the page
 * loader share one webpack/turbopack chunk.
 */
export function prefetchStudio(mode: StudioPrefetchMode): void {
  switch (mode) {
    case 'video_creation':
      void import('@/components/studio/video-generation-studio');
      return;
    case 'audio_generation':
      void import('@/components/studio/audio-generation-studio');
      return;
    case 'music_generation':
      void import('@/components/studio/music-generation-studio');
      return;
  }
}
