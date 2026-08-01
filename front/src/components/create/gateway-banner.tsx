import { getTranslations } from 'next-intl/server';

import { IconSparkle } from '@/components/ui/icons';
import type { GatewayStatus } from '@/lib/api/types';

/**
 * The "smart gateway is working" banner from the create page.
 *
 * The numbers come from the router's own statistics rather than from copy, so
 * a degraded gateway shows as degraded here instead of only in the ops
 * console — which the plan requires.
 */
export async function GatewayBanner({ status }: { status: GatewayStatus | null }) {
  const t = await getTranslations('gateway');
  if (!status) return null;

  const tone =
    status.status === 'healthy'
      ? 'text-success'
      : status.status === 'degraded'
        ? 'text-amber'
        : 'text-danger';

  return (
    <section className="gateway-panel rounded-[var(--radius-lg)] border border-border p-5 sm:p-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex gap-4">
          <span className="grid size-11 shrink-0 place-items-center rounded-full bg-success/12 text-success">
            <IconSparkle className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="eyebrow">{t('eyebrow')}</p>
            <h2 className="mt-1 text-lg font-semibold">{t('title')}</h2>
            <p className="mt-1.5 max-w-2xl text-sm text-muted">{t('description')}</p>
          </div>
        </div>

        <dl className="grid shrink-0 grid-cols-3 gap-3 text-center">
          <Metric value={String(status.available_routes)} label={t('routes')} />
          <Metric value={`${status.savings_percent}%`} label={t('savings')} />
          <Metric
            value={t(
              status.status === 'healthy'
                ? 'healthy'
                : status.status === 'degraded'
                  ? 'degraded'
                  : 'down',
            )}
            label={t('status')}
            valueClassName={tone}
          />
        </dl>
      </div>

      {status.status === 'degraded' ? (
        <p
          role="status"
          className="mt-4 rounded-[var(--radius-sm)] bg-amber/10 px-3 py-2 text-xs text-amber"
        >
          {t('degradedNotice')}
        </p>
      ) : null}
    </section>
  );
}

function Metric({
  value,
  label,
  valueClassName,
}: {
  value: string;
  label: string;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-border bg-surface/60 px-4 py-2.5">
      <dt className="sr-only">{label}</dt>
      <dd className={`tabular text-base font-semibold ${valueClassName ?? ''}`}>{value}</dd>
      <p aria-hidden="true" className="mt-0.5 text-[11px] text-muted">
        {label}
      </p>
    </div>
  );
}
