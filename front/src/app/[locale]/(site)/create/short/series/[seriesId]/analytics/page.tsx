import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { SeriesAnalyticsDetail } from '@/features/drama-dashboard/series-analytics-detail';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('seriesAnalyticsDetailTitle'), description: t('dashboardSubtitle') };
}

/**
 * `/create/short/series/{seriesId}/analytics`: the per-episode × per-channel
 * breakdown behind the overview card on the series page. Same thin server
 * wrapper pattern as `series/[seriesId]/page.tsx` — the client component
 * fetches the series/metrics itself.
 */
export default async function SeriesAnalyticsDetailPage({
  params,
}: {
  params: Promise<{ seriesId: string }>;
}) {
  const t = await getTranslations('editor');
  const { seriesId } = await params;
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <BackLink href={`/create/short/series/${seriesId}`}>{t('backToSeries')}</BackLink>
      <SeriesAnalyticsDetail seriesId={seriesId} />
    </div>
  );
}
