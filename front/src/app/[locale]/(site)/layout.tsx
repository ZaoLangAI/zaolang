import { Suspense } from 'react';
import { getTranslations, setRequestLocale } from 'next-intl/server';

import { LoginDialog } from '@/components/auth/login-dialog';
import { CommandPaletteHost } from '@/components/command/command-palette-host';
import { SiteFooter } from '@/components/layout/site-footer';
import { TopBar } from '@/components/layout/top-bar';

export default async function SiteLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('nav');

  return (
    <div className="flex min-h-dvh flex-col">
      {/* First tab stop on every page, so keyboard users are not forced
          through the whole navigation to reach the content. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-[var(--radius-sm)] focus:bg-surface-raised focus:px-4 focus:py-2 focus:text-sm"
      >
        {t('skipToContent')}
      </a>
      <Suspense fallback={<div className="h-16 border-b border-border" aria-hidden="true" />}>
        <TopBar />
      </Suspense>
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooter />
      <LoginDialog />
      <CommandPaletteHost />
    </div>
  );
}
