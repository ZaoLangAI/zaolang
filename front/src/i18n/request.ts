import { hasLocale } from 'next-intl';
import { getRequestConfig } from 'next-intl/server';

import { defaultLocale, routing } from '@/i18n/routing';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : defaultLocale;

  return {
    locale,
    messages: (await import(`@/i18n/messages/${locale}.json`)).default,
    // Fixed so server and client format identically; the visible timezone is a
    // user preference rendered client-side, not a formatting default.
    timeZone: 'UTC',
    now: new Date(),
  };
});
