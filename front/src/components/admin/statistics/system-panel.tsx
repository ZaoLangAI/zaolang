'use client';

import { useLocale, useTranslations } from 'next-intl';

import { Badge, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { StorageUsage, SystemHealth } from '@/lib/api/admin-types';
import { cn } from '@/lib/cn';
import { formatBytes, formatNumber } from '@/lib/format';

/**
 * Queue depth and storage usage are live gauges, not a stored time series —
 * there is no historical sample table to chart a trend from, so this tab
 * stays a snapshot like the health page it borrows vocabulary from.
 */
export function SystemPanel({
  health,
  storageUsage,
}: {
  health: SystemHealth;
  storageUsage: StorageUsage;
}) {
  const t = useTranslations('adminHealth');
  const tData = useTranslations('adminData');
  const locale = useLocale() as Locale;
  const byPrefix = Object.entries(storageUsage.by_prefix ?? {});

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('dependencies')}</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {health.services.map((service) => (
            <li
              key={service.name}
              className="rounded-[var(--radius-md)] border border-border bg-surface p-4"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-mono text-sm">{service.name}</p>
                <Badge tone={service.healthy ? 'success' : 'danger'}>
                  {service.healthy ? t('up') : t('down')}
                </Badge>
              </div>
              <p className="tabular mt-2 text-xs text-muted">
                {service.healthy
                  ? t('latency', { ms: formatNumber(Math.round(service.latency_ms ?? 0), locale) })
                  : (service.detail ?? '')}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold">{t('queues')}</h2>
        <ul className="flex flex-col divide-y divide-border text-sm">
          {health.queues.map((queue) => (
            <li key={queue.queue} className="flex items-center justify-between gap-3 py-2">
              <span className="font-mono text-xs">{queue.queue}</span>
              <span
                className={cn(
                  'tabular text-xs',
                  queue.depth < 0
                    ? 'text-danger'
                    : queue.depth > 50
                      ? 'text-amber'
                      : 'text-muted',
                )}
              >
                {queue.depth < 0 ? t('down') : `${t('queueDepth')} ${queue.depth}`}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{tData('storage')}</h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={storageUsage.bucket} label={tData('bucket')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(storageUsage.object_count, locale)}
              label={tData('objectCount')}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatBytes(storageUsage.total_bytes, locale)}
              label={tData('totalSize')}
            />
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
    </div>
  );
}
