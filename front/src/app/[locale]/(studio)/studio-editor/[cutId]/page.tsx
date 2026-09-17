import { getTranslations } from 'next-intl/server';

import { DramaEditor } from '@/features/editor/drama-editor';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('title') };
}

export default async function StudioEditorPage({
  params,
  searchParams,
}: {
  params: Promise<{ cutId: string }>;
  searchParams: Promise<{ draftId?: string }>;
}) {
  const { cutId } = await params;
  const { draftId } = await searchParams;
  return <DramaEditor cutId={cutId} draftId={draftId ?? null} />;
}
