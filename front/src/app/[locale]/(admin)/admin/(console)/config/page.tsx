import { getTranslations } from 'next-intl/server';

import { RuntimeConfigPanel } from '@/components/admin/config/runtime-config-panel';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue, Page } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminConfig');
  return { title: t('title') };
}

export default async function AdminConfigPage() {
  const t = await getTranslations('adminConfig');

  const config = await adminFetch<Page<ConfigValue>>('/v1/admin/config');
  const byKey = Object.fromEntries(config.items.map((item) => [item.key, item]));

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <RuntimeConfigPanel
        initial={byKey.feature_flags!}
        kind="feature_flags"
        title={t('featureFlags')}
      />
      <RuntimeConfigPanel
        initial={byKey.shortform!}
        kind="shortform"
        title={t('shortformProfiles')}
      />
      {byKey.asset_consistency ? (
        <RuntimeConfigPanel
          initial={byKey.asset_consistency}
          kind="asset_consistency"
          title={t('assetConsistency')}
        />
      ) : null}
    </div>
  );
}
