import { getTranslations } from 'next-intl/server';

import { DuplicateGroups } from '@/components/admin/moderation/duplicate-groups';
import { ModerationQueue } from '@/components/admin/moderation/moderation-queue';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminModeration');
  return { title: t('title') };
}

export default async function AdminModerationPage() {
  const t = await getTranslations('adminModeration');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <ModerationQueue />
      <DuplicateGroups />
    </div>
  );
}
