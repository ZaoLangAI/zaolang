import { getTranslations } from 'next-intl/server';

import { ReportsConsole } from '@/components/admin/reports/reports-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminReports');
  return { title: t('title') };
}

export default async function AdminReportsPage() {
  const t = await getTranslations('adminReports');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <ReportsConsole />
    </div>
  );
}
