import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { CanvasLibrary } from '@/features/canvas/canvas-library';

export async function generateMetadata() {
  const t = await getTranslations('canvas');
  return { title: t('libraryTitle'), description: t('librarySubtitle') };
}

export default async function CanvasLibraryPage() {
  const t = await getTranslations('canvas');
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <PageHeading
        eyebrow={t('eyebrow')}
        title={t('libraryTitle')}
        description={t('librarySubtitle')}
      />
      <CanvasLibrary />
    </div>
  );
}
