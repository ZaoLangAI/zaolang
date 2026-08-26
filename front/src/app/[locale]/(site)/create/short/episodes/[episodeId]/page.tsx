import { getTranslations } from 'next-intl/server';

import { EpisodePanel } from '@/features/drama-dashboard/episode-panel';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('dashboardTitle'), description: t('dashboardSubtitle') };
}

/**
 * `/create/short/episodes/{episodeId}`: a thin server wrapper. `EpisodePanel`
 * renders its own back link once it knows the episode's `series_id` (only
 * available after the client fetch resolves), so this page supplies nothing
 * else.
 */
export default async function EpisodeDetailPage({
  params,
}: {
  params: Promise<{ episodeId: string }>;
}) {
  const { episodeId } = await params;
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <EpisodePanel episodeId={episodeId} />
    </div>
  );
}
