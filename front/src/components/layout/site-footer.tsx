import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';

const SOURCE_URL = process.env.NEXT_PUBLIC_SOURCE_URL ?? 'https://github.com/ZaoLangAI/zaolang';
const VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? '0.0.0-dev';

/**
 * AGPL section 13 obliges a network-facing deployment to offer its users the
 * corresponding source, so the link and the running version are part of the
 * page rather than buried in a docs site.
 */
export function SiteFooter() {
  const t = useTranslations('footer');
  const tNav = useTranslations('nav');

  return (
    <footer className="mt-16 border-t border-border">
      <div className="page-x mx-auto flex max-w-[1440px] flex-col gap-3 py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-xl">{t('sourceNotice')}</p>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <a
            href={SOURCE_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="text-text underline-offset-4 hover:underline"
          >
            {t('source')}
          </a>
          <span>{t('license')}</span>
          <Link href="/learn" className="hover:text-text">
            {tNav('learn')}
          </Link>
          <span className="tabular">{t('version', { version: VERSION })}</span>
        </nav>
      </div>
    </footer>
  );
}
