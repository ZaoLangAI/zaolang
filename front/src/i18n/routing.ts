import { defineRouting } from 'next-intl/routing';

export const locales = ['zh-CN', 'en', 'ja'] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = 'zh-CN';

/**
 * Region is deliberately separate from locale: a reader in Japan may want the
 * Chinese interface, and pricing has to follow where they are rather than what
 * they read. The values mirror the backend `Region` enum.
 */
export const regions = ['CN', 'GLOBAL', 'JP'] as const;
export type Region = (typeof regions)[number];

export const defaultRegion: Region = 'CN';

export const regionCurrency: Record<Region, string> = {
  CN: 'CNY',
  GLOBAL: 'USD',
  JP: 'JPY',
};

export const routing = defineRouting({
  locales,
  defaultLocale,
  // Always prefixed so `<html lang>` is decided by the URL alone, which keeps
  // shared links and crawler output unambiguous.
  localePrefix: 'always',
  localeCookie: { name: 'zl_locale', maxAge: 60 * 60 * 24 * 365 },
});

export function isLocale(value: string | undefined): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}

export function isRegion(value: string | undefined): value is Region {
  return !!value && (regions as readonly string[]).includes(value);
}
