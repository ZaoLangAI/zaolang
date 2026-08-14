import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';

const VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? '0.0.0-dev';

/** Branding and the running build version. Not a source-code offer. */
export function SiteFooter() {
  const t = useTranslations('footer');
  const tNav = useTranslations('nav');

  return (
    <footer className="mt-16 border-t border-border">
      <div className="page-x mx-auto flex max-w-[1440px] flex-col gap-3 py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Link href="/learn" className="hover:text-text">
            {tNav('learn')}
          </Link>
          <span className="tabular">{t('version', { version: VERSION })}</span>
        </nav>
      </div>
    </footer>
  );
}
