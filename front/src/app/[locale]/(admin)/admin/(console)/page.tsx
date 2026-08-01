import { getTranslations } from 'next-intl/server';

import { HealthCards } from '@/components/admin/health/health-cards';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch, adminFetchOrNull } from '@/lib/api/admin-server';
import type {
  DanglingReserve,
  ModerationItem,
  Page,
  ReportCase,
  SystemHealth,
} from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminHealth');
  return { title: t('title') };
}

export default async function AdminHealthPage() {
  const t = await getTranslations('adminHealth');

  // Every panel degrades independently: a Redis outage must not blank the page
  // that exists to tell you Redis is down.
  const [health, dangling, moderation, reports] = await Promise.all([
    adminFetch<SystemHealth>('/v1/admin/health'),
    adminFetchOrNull<Page<DanglingReserve>>('/v1/admin/credits/dangling'),
    adminFetchOrNull<Page<ModerationItem>>('/v1/admin/moderation/queue', {
      query: { limit: 1 },
    }),
    adminFetchOrNull<Page<ReportCase>>('/v1/admin/reports', { query: { limit: 1 } }),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <HealthCards
        health={health}
        danglingCount={dangling?.items.length ?? 0}
        pendingModeration={moderation?.items.length ?? 0}
        openReports={reports?.items.length ?? 0}
      />
    </div>
  );
}
