import { getTranslations } from 'next-intl/server';

import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { DashboardShell } from '@/features/drama-dashboard/dashboard-shell';

export async function generateMetadata() {
  const t = await getTranslations('editor');
  return { title: t('dashboardTitle'), description: t('dashboardSubtitle') };
}

/**
 * `/create/short`: the drama-series management dashboard — every series the
 * user owns, and a form to start a new one. This replaced the old single-clip
 * short-video studio, which now lives at `/create/short/studio`, and folded
 * in what used to be the separate `/create/drama` landing page.
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
