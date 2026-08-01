import { getTranslations } from 'next-intl/server';

import { DataRequestsPanel } from '@/components/admin/users/data-requests-panel';
import { UsersConsole } from '@/components/admin/users/users-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminUsers');
  return { title: t('title') };
}

export default async function AdminUsersPage() {
  const t = await getTranslations('adminUsers');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <UsersConsole />
      <DataRequestsPanel />
    </div>
  );
}
