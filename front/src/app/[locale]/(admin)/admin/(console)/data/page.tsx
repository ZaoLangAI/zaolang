import { getLocale, getTranslations } from 'next-intl/server';

import { BackupsPanel } from '@/components/admin/data/backups-panel';
import { LifecyclePanel } from '@/components/admin/data/lifecycle-panel';
import { SeedPanel } from '@/components/admin/data/seed-panel';
import { PageHeading, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminFetch } from '@/lib/api/admin-server';
import type { StorageUsage } from '@/lib/api/admin-types';
import { formatBytes, formatNumber } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('adminData');
  return { title: t('title') };
}

export default async function AdminDataPage() {
  const t = await getTranslations('adminData');
  const locale = (await getLocale()) as Locale;

  const usage = await adminFetch<StorageUsage>('/v1/admin/storage/usage');
  const byPrefix = Object.entries(usage.by_prefix ?? {});

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('storage')}</h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={usage.bucket} label={t('bucket')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatNumber(usage.object_count, locale)} label={t('objectCount')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatBytes(usage.total_bytes, locale)} label={t('totalSize')} />
          </li>
        </ul>

        {byPrefix.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-2">
            {byPrefix.map(([prefix, bytes]) => (
              <li
                key={prefix}
                className="rounded-full border border-border px-3 py-1 text-xs text-muted"
              >
                <span className="font-mono">{prefix}</span> {formatBytes(Number(bytes), locale)}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <LifecyclePanel rules={usage.lifecycle_rules ?? []} />
      <BackupsPanel />
      <SeedPanel />
    </div>
  );
}
