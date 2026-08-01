import { getLocale, getTranslations } from 'next-intl/server';

import { IconSparkle } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { formatCount } from '@/lib/format';

/** Balance card in the create page header, with the route into billing. */
export async function CreditsTile({ available }: { available: number | null }) {
  const t = await getTranslations('credits');
  const tAuth = await getTranslations('auth');
  const locale = (await getLocale()) as Locale;

  return (
    <div className="flex shrink-0 items-center gap-4 rounded-[var(--radius-md)] border border-border bg-surface px-5 py-4">
      <IconSparkle className="size-6 text-amber" />
      <div>
        <p className="text-[11px] text-muted">{t('balance')}</p>
        <p className="tabular text-2xl font-semibold">
          {available === null ? '—' : formatCount(available, locale)}
        </p>
      </div>
      <Link href="/billing" className="ml-4 text-xs text-primary hover:underline">
        {available === null ? tAuth('signIn') : t('manage')}
      </Link>
    </div>
  );
}
