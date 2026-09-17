import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { SeriesDetail } from '@/features/drama-dashboard/series-detail';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('dashboardTitle'), description: t('dashboardSubtitle') };
}

/**
 * `/create/short/series/{seriesId}`: a thin server wrapper. `SeriesDetail`
 * fetches the series itself and renders its own heading, so this only
 * supplies the back link — the series' title is not known until the client
 * fetch resolves.
 */
export default async function SeriesDetailPage({
  params,
}: {
  params: Promise<{ seriesId: string }>;
}) {
  const t = await getTranslations('editor');
  const { seriesId } = await params;
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <BackLink href="/create/short">{t('backToDashboard')}</BackLink>
      <SeriesDetail seriesId={seriesId} />
    </div>
  );
}
