import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { RemixUnlockGate } from '@/components/marketplace/remix-unlock-gate';
import { AudioGenerationStudio } from '@/components/studio/audio-generation-studio';
import { ImageGenerationStudio } from '@/components/studio/image-generation-studio';
import { VideoGenerationStudio } from '@/components/studio/video-generation-studio';
import { BackLink } from '@/components/ui/back-link';
import { getWork } from '@/lib/api/work-loaders';
import type { ReusableParams, WorkDetail } from '@/lib/api/types';

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
        <RemixStudio work={work} reusableParams={work.reusable_params} />
      ) : (
        <RemixUnlockGate work={work} />
      )}
    </div>
  );
}

/**
 * Picks the studio that actually matches the source's own medium, rather
 * than always handing every remix to `VideoGenerationStudio` — a photo
 * remixed "into a video" and a voiceover remixed "into a video" were both
 * silently wrong operations, not a real choice the author or the licence
 * ever made. `ImageGenerationStudio`/`AudioGenerationStudio` both already
 * accept `source`/`reference`; only the image branch needs the studio to
 * also pull the source's own asset into its reference upload (see that
 * studio's own `sourceMaterialSeededRef` effect) — a video source gets that
 * for free server-side (`attach_licensed_source_video`).
 */
function RemixStudio({
  work,
  reusableParams,
}: {
  work: WorkDetail;
  reusableParams: ReusableParams;
}) {
  const mediaType = work.media_type ?? work.current_version?.media_type;
  const source = { work, params: reusableParams };

  if (mediaType === 'image') {
    return <ImageGenerationStudio source={source} />;
  }
  if (mediaType === 'audio') {
    return <AudioGenerationStudio source={source} />;
  }
  return <VideoGenerationStudio operation="video_to_video" source={source} />;
}
