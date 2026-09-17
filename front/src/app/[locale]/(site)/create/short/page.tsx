import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { DashboardShell } from '@/features/drama-dashboard/dashboard-shell';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('dashboardTitle'), description: t('dashboardSubtitle') };
}

/**
 * `/create/short`: the sole entry point for short-drama creation — a
 * searchable, sortable card library of every `kind=drama` series the user
 * owns, plus the "新建短剧" dialog. This replaced the old single-clip
 * `ShortformStudio` (`/create/short/studio`), which has been removed —
 * episodes are now only ever created through "文案创作" (`/create/script`).
 */
export default async function ShortDashboardPage() {
  const t = await getTranslations('editor');
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <PageHeading
        eyebrow={t('dashboardEyebrow')}
        title={t('dashboardTitle')}
        description={t('dashboardSubtitle')}
      />
      <DashboardShell />
    </div>
  );
}
