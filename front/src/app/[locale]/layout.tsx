import type { Metadata, Viewport } from 'next';
import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { cookies } from 'next/headers';
import { notFound } from 'next/navigation';

import { AppProviders } from '@/components/app-providers';
import { routing } from '@/i18n/routing';
import {
  MOTION_COOKIE,
  THEME_COOKIE,
  defaultTheme,
  isThemePreference,
  themeColor,
  themeInitScript,
} from '@/lib/theme';

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export const viewport: Viewport = {
  // Overwritten client-side when the theme resolves; this is the value the
  // browser uses for the very first paint.
  themeColor: themeColor.dark,
  width: 'device-width',
  initialScale: 1,
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'brand' });
  return {
    title: { default: t('name'), template: `%s · ${t('name')}` },
    description: t('tagline'),
    icons: { icon: '/favicon.svg' },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  const jar = await cookies();
  const cookieTheme = jar.get(THEME_COOKIE)?.value;
  const preference = isThemePreference(cookieTheme) ? cookieTheme : defaultTheme;
  const reduceMotion = jar.get(MOTION_COOKIE)?.value === 'true';

  // `dark` and `light` render straight from the cookie with no flash. `system`
  // cannot be resolved on the server, so it is painted dark (the design
  // baseline) and corrected by the inline script before first paint.
  const serverTheme = preference === 'system' ? 'dark' : preference;

  return (
    <html
      lang={locale}
      data-theme={serverTheme}
      data-theme-preference={preference}
      data-reduced-motion={String(reduceMotion)}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-dvh antialiased">
        <NextIntlClientProvider>
          <AppProviders initialPreference={preference} initialReduceMotion={reduceMotion}>
            {children}
          </AppProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
