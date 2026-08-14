import { getTranslations } from 'next-intl/server';

import { DramaEditor } from '@/features/editor/drama-editor';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('title'), description: t('subtitle') };
}

export default async function DramaCutPage({
  params,
  searchParams,
}: {
  params: Promise<{ cutId: string }>;
  searchParams: Promise<{ draftId?: string }>;
}) {
  const t = await getTranslations('editor');
  const { cutId } = await params;
  const { draftId } = await searchParams;
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-8 sm:px-6">
      <BackLink href="/create/drama">{t('backToDrama')}</BackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <DramaEditor cutId={cutId} draftId={draftId ?? null} />
    </div>
  );
}
