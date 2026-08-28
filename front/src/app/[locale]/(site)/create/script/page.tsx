import { getTranslations } from 'next-intl/server';

import { GoBackLink } from '@/components/ui/go-back-link';
import { ScriptLanding } from '@/features/script/script-landing';

export async function generateMetadata() {
  const t = await getTranslations('scriptStudio');
  return { title: t('title'), description: t('subtitle') };
}

const IDEA_PREFILL_MAX_LENGTH = 2000;

export default async function ScriptStudioPage({
  searchParams,
}: {
  searchParams: Promise<{ seriesId?: string; ideaPrefill?: string }>;
}) {
  const tActions = await getTranslations('actions');
  const { seriesId, ideaPrefill } = await searchParams;
  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <GoBackLink fallbackHref="/create">{tActions('back')}</GoBackLink>
      <ScriptLanding
        seriesId={seriesId}
        initialIdea={ideaPrefill?.trim().slice(0, IDEA_PREFILL_MAX_LENGTH) || undefined}
      />
    </div>
  );
}
