import { getTranslations } from 'next-intl/server';

import { ConfigConsole } from '@/components/admin/config/config-console';
import { FeatureFlagsPanel } from '@/components/admin/config/feature-flags-panel';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue, FeatureFlag, Page } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminConfig');
  return { title: t('title') };
}

export default async function AdminConfigPage() {
  const t = await getTranslations('adminConfig');

  const [config, flags] = await Promise.all([
    adminFetch<Page<ConfigValue>>('/v1/admin/config'),
    adminFetch<Page<FeatureFlag>>('/v1/admin/feature-flags'),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <ConfigConsole initial={config.items} />
      <FeatureFlagsPanel flags={flags.items} />
    </div>
  );
}
