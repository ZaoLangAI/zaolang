import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { RemixUnlockGate } from '@/components/marketplace/remix-unlock-gate';
import { VideoGenerationStudio } from '@/components/studio/video-generation-studio';
import { BackLink } from '@/components/ui/back-link';
import { getWork } from '@/lib/api/work-loaders';

interface Params {
  params: Promise<{ workId: string }>;
}

export async function generateMetadata({ params }: Params) {
  const { workId } = await params;
  const work = await getWork(workId, true);
  const t = await getTranslations('remixPage');
  return { title: work ? t('titleFrom', { title: work.title }) : t('eyebrow') };
}

export default async function RemixPage({ params }: Params) {
  const { workId } = await params;
  const t = await getTranslations('remixPage');

  const work = await getWork(workId, true);
  if (!work) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-5 px-4 py-6 sm:px-6">
      <BackLink href={`/work/${work.id}`}>{t('backToSource')}</BackLink>

      <header>
        <p className="eyebrow">{t('eyebrow')}</p>
        <h1 className="mt-1.5 text-3xl font-bold tracking-tight sm:text-4xl">
          {t('titleFrom', { title: work.title })}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
      </header>

      {work.can_remix && work.reusable_params ? (
        <VideoGenerationStudio
          operation="image_to_video"
          source={{ work, params: work.reusable_params }}
        />
      ) : (
        <RemixUnlockGate work={work} />
      )}
    </div>
  );
}
