import { getTranslations } from 'next-intl/server';

import { StyleGalleryConsole } from '@/components/admin/style-gallery/style-gallery-console';
import { PageHeading } from '@/components/ui/primitives';

export async function generateMetadata() {
  const t = await getTranslations('adminStyleGallery');
  return { title: t('title') };
}

export default async function AdminStyleGalleryPage() {
  const t = await getTranslations('adminStyleGallery');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <StyleGalleryConsole />
    </div>
  );
}
