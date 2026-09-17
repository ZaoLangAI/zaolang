import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { VideoAnalysisStudio } from '@/features/video-analysis/video-analysis-studio';

export async function generateMetadata() {
  const t = await getTranslations('videoAnalysisPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function VideoAnalysisPage() {
  const t = await getTranslations('videoAnalysisPage');
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <VideoAnalysisStudio />
    </div>
  );
}
