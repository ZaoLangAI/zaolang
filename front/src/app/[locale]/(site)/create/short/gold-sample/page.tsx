import { getTranslations } from 'next-intl/server';

import { GoldSample } from '@/features/editor/gold-sample';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  // Internal QA harness, not a product surface: kept reachable by direct URL
  // (the e2e suite exercises it against a production build) but excluded
  // from search indexing and never linked from product navigation.
  return { title: t('goldTitle'), description: t('goldHint'), robots: { index: false, follow: false } };
}

export default async function DramaGoldSamplePage() {
  const t = await getTranslations('editor');
  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-6 px-4 py-8 sm:px-6">
      <PageHeading eyebrow={t('eyebrow')} title={t('goldTitle')} description={t('goldHint')} />
      <GoldSample />
    </div>
  );
}
