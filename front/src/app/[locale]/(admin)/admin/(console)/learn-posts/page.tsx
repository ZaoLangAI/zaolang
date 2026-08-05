import { getTranslations } from 'next-intl/server';

import { LearnPostsConsole } from '@/components/admin/learn-posts/learn-posts-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('admin');
  return { title: t('learnPostsTitle') };
}

export default async function AdminLearnPostsPage() {
  const t = await getTranslations('admin');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('learnPostsTitle')} description={t('learnPostsSubtitle')} />
      <LearnPostsConsole />
    </div>
  );
}
