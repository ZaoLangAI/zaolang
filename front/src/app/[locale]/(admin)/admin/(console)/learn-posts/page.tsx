import { getTranslations } from 'next-intl/server';

import { LearnPostsConsole } from '@/components/admin/learn-posts/learn-posts-console';
import { RuntimeConfigDialog } from '@/components/admin/config/runtime-config-dialog';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('admin');
  return { title: t('learnPostsTitle') };
}

export default async function AdminLearnPostsPage() {
  const t = await getTranslations('admin');
  const tConfig = await getTranslations('adminConfig');
  const moderation = await adminFetch<ConfigValue>('/v1/admin/config/learning_moderation');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('learnPostsTitle')} description={t('learnPostsSubtitle')} />
      <LearnPostsConsole
        configAction={
          <RuntimeConfigDialog
            title={tConfig('learningRules')}
            items={[{ initial: moderation, kind: 'moderation', title: tConfig('learningRules') }]}
          />
        }
      />
    </div>
  );
}
