import { getLocale, getTranslations } from 'next-intl/server';

import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { LedgerEntry } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatDateTime, formatNumber } from '@/lib/format';

const TYPE_KEYS = {
  grant: 'typeGrant',
  purchase: 'typePurchase',
  reserve: 'typeReserve',
  capture: 'typeCapture',
  release: 'typeRelease',
  refund: 'typeRefund',
  adjustment: 'typeAdjustment',
  royalty_in: 'typeRoyaltyIn',
  royalty_out: 'typeRoyaltyOut',
} as const;

/**
 * The append-only ledger, shown as it is stored.
 *
 * Reserve and release rows are not hidden even though they net to zero: they
 * are the reason a balance can drop and come back, and hiding them would make
 * the arithmetic look wrong.
 */
export async function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  const t = await getTranslations('billingPage');
  const locale = (await getLocale()) as Locale;

  if (entries.length === 0) {
    return (
      <section>
        <SectionHeading title={t('ledger')} />
        <EmptyState title={t('ledgerEmpty')} />
      </section>
    );
  }

  return (
    <section>
      <SectionHeading title={t('ledger')} />
      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-surface-soft text-xs text-muted">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">
                {t('colTime')}
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                {t('colType')}
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                {t('colAmount')}
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                {t('colBalance')}
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                {t('colNote')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td className="tabular whitespace-nowrap px-4 py-3 text-xs text-muted">
                  {formatDateTime(entry.created_at, locale)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-xs">
                  {t(TYPE_KEYS[entry.type as keyof typeof TYPE_KEYS] ?? 'typeAdjustment')}
                </td>
                <td
                  className={cn(
                    'tabular whitespace-nowrap px-4 py-3 text-right',
                    entry.amount > 0 ? 'text-success' : 'text-text',
                  )}
                >
                  {entry.amount > 0 ? '+' : ''}
                  {formatNumber(entry.amount, locale)}
                </td>
                <td className="tabular whitespace-nowrap px-4 py-3 text-right text-muted">
                  {formatNumber(entry.balance_after, locale)}
                </td>
                <td className="px-4 py-3 text-xs text-muted">{entry.reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
