import { getLocale, getTranslations } from 'next-intl/server';

import { Badge, StatTile } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { SystemHealth } from '@/lib/api/admin-types';
import { cn } from '@/lib/cn';
import { formatDateTime, formatNumber } from '@/lib/format';

export async function HealthCards({
  health,
  danglingCount,
  pendingModeration,
  openReports,
}: {
  health: SystemHealth;
  danglingCount: number;
  pendingModeration: number;
  openReports: number;
}) {
  const t = await getTranslations('adminHealth');
  const locale = (await getLocale()) as Locale;

  return (
    <div className="flex flex-col gap-5">
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

      <section className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold">{t('queues')}</h2>
          <ul className="flex flex-col divide-y divide-border text-sm">
            {health.queues.map((queue) => (
              <li key={queue.queue} className="flex items-center justify-between gap-3 py-2">
                <span className="font-mono text-xs">{queue.queue}</span>
                <span
                  className={cn(
                    'tabular text-xs',
                    // -1 means the depth could not be read, which is a
                    // different problem from an empty queue.
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
        </div>

        <div className="flex flex-col gap-3">
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">{t('llmGateway')}</h2>
            <p className="mt-2 flex items-center gap-2 text-xs">
              <Badge
                tone={
                  health.llm_reachable === null
                    ? 'neutral'
                    : health.llm_reachable
                      ? 'success'
                      : 'danger'
                }
              >
                {health.llm_reachable === null
                  ? t('degraded')
                  : health.llm_reachable
                    ? t('up')
                    : t('down')}
              </Badge>
              <span className="text-muted">
                {t('llmMode')}: <span className="font-mono">{health.llm_mode}</span>
              </span>
            </p>
            <p className="mt-3 text-xs text-muted">
              {t('alembic')}:{' '}
              <span className="font-mono">{health.alembic_revision ?? t('down')}</span>
            </p>
            <p className="mt-1 text-xs text-muted">
              {formatDateTime(health.generated_at, locale)} · v{health.app_version}
            </p>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 divide-x divide-border overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface lg:grid-cols-3">
        <Link href="/admin/credits" className="hover:bg-surface-soft">
          <StatTile
            value={formatNumber(danglingCount, locale)}
            label={t('dangling')}
            hint={t('danglingHint')}
            tone={danglingCount > 0 ? 'danger' : undefined}
          />
        </Link>
        <Link href="/admin/moderation" className="hover:bg-surface-soft">
          <StatTile
            value={formatNumber(pendingModeration, locale)}
            label={t('pendingModeration')}
          />
        </Link>
        <Link href="/admin/reports" className="hover:bg-surface-soft">
          <StatTile value={formatNumber(openReports, locale)} label={t('openReports')} />
        </Link>
      </section>
    </div>
  );
}
