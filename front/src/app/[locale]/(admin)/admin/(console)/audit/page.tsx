import { getTranslations } from 'next-intl/server';

import { AuditConsole } from '@/components/admin/audit/audit-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminAudit');
  return { title: t('title') };
}

export default async function AdminAuditPage() {
  const t = await getTranslations('adminAudit');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <AuditConsole />
    </div>
  );
}
