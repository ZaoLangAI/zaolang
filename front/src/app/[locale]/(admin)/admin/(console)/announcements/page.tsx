import { getTranslations } from 'next-intl/server';

import { AnnouncementsConsole } from '@/components/admin/announcements/announcements-console';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { Announcement, Page } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminAnnouncements');
  return { title: t('title') };
}

export default async function AdminAnnouncementsPage() {
  const t = await getTranslations('adminAnnouncements');
  const list = await adminFetch<Page<Announcement>>('/v1/admin/announcements');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <AnnouncementsConsole initial={list.items} />
    </div>
  );
}
