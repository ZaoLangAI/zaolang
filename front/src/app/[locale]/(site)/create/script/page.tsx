import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { ScriptLanding } from '@/features/script/script-landing';

export async function generateMetadata() {
  const t = await getTranslations('scriptStudio');
  return { title: t('title'), description: t('subtitle') };
}

export default async function ScriptStudioPage() {
  const t = await getTranslations('scriptStudio');
  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <ScriptLanding />
    </div>
  );
}
