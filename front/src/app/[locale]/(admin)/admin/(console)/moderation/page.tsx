import { getTranslations } from 'next-intl/server';

import { DuplicateGroups } from '@/components/admin/moderation/duplicate-groups';
import { ModerationQueue } from '@/components/admin/moderation/moderation-queue';
import { RuntimeConfigDialog } from '@/components/admin/config/runtime-config-dialog';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminModeration');
  return { title: t('title') };
}

export default async function AdminModerationPage() {
  const t = await getTranslations('adminModeration');
  const tConfig = await getTranslations('adminConfig');
  const moderation = await adminFetch<ConfigValue>('/v1/admin/config/content_moderation');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <ModerationQueue
        configAction={
          <RuntimeConfigDialog
            title={tConfig('contentRules')}
            items={[{ initial: moderation, kind: 'moderation', title: tConfig('contentRules') }]}
          />
        }
      />
      <DuplicateGroups />
    </div>
  );
}
