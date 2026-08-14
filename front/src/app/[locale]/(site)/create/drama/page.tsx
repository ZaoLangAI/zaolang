import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { DramaLanding } from '@/features/editor/drama-landing';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('title'), description: t('subtitle') };
}

export default async function DramaStudioPage() {
  const t = await getTranslations('editor');
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <DramaLanding />
    </div>
  );
}
