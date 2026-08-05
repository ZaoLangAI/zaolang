import { getTranslations } from 'next-intl/server';

import { SkillLibraryConsole } from '@/components/admin/skill-library/skill-library-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminSkillLibrary');
  return { title: t('title') };
}

export default async function AdminSkillLibraryPage() {
  const t = await getTranslations('adminSkillLibrary');
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <SkillLibraryConsole />
    </div>
  );
}
