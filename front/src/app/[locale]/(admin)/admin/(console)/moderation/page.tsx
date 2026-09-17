import { getTranslations } from 'next-intl/server';

import { RuntimeConfigDialog } from '@/components/admin/config/runtime-config-dialog';
import {
  ModerationWorkspace,
  type ModerationTab,
} from '@/components/admin/moderation/moderation-workspace';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue } from '@/lib/api/admin-types';

const TABS: readonly ModerationTab[] = ['queue', 'reports', 'appeals'];

export async function generateMetadata() {
  const t = await getTranslations('adminModeration');
  return { title: t('title') };
}

export default async function AdminModerationPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const t = await getTranslations('adminModeration');
  const tConfig = await getTranslations('adminConfig');
  const { tab } = await searchParams;
  const initialTab = TABS.find((candidate) => candidate === tab) ?? 'queue';
  const moderation = await adminFetch<ConfigValue>('/v1/admin/config/content_moderation');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <ModerationWorkspace
        initialTab={initialTab}
        configAction={
          <RuntimeConfigDialog
            title={tConfig('contentRules')}
            items={[{ initial: moderation, kind: 'moderation', title: tConfig('contentRules') }]}
          />
        }
      />
    </div>
  );
}
