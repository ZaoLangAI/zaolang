import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { ScriptEditor } from '@/features/script/script-editor';

export async function generateMetadata() {
  const t = await getTranslations('scriptStudio');
  return { title: t('title'), description: t('subtitle') };
}

export default async function ScriptEditorPage({
  params,
}: {
  params: Promise<{ episodeId: string }>;
}) {
  const t = await getTranslations('scriptStudio');
  const { episodeId } = await params;
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-8 sm:px-6">
      <BackLink href="/create/script">{t('backToScripts')}</BackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <ScriptEditor episodeId={episodeId} />
    </div>
  );
}
