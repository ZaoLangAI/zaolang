import { getTranslations } from 'next-intl/server';

import { JobsConsole } from '@/components/admin/jobs/jobs-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminJobs');
  return { title: t('title') };
}

export default async function AdminJobsPage() {
  const t = await getTranslations('adminJobs');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <JobsConsole />
    </div>
  );
}
