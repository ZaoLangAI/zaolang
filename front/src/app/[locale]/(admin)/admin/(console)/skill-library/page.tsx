import { getTranslations } from 'next-intl/server';

import { SkillLibraryConsole } from '@/components/admin/skill-library/skill-library-console';
import { RuntimeConfigDialog } from '@/components/admin/config/runtime-config-dialog';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { ConfigValue } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminSkillLibrary');
  return { title: t('title') };
}

export default async function AdminSkillLibraryPage() {
  const t = await getTranslations('adminSkillLibrary');
  const tConfig = await getTranslations('adminConfig');
  const moderation = await adminFetch<ConfigValue>('/v1/admin/config/skill_moderation');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <SkillLibraryConsole
        configAction={
          <RuntimeConfigDialog
            title={tConfig('skillRules')}
            items={[{ initial: moderation, kind: 'moderation', title: tConfig('skillRules') }]}
          />
        }
      />
    </div>
  );
}
