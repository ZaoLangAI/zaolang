import { hasLocale } from 'next-intl';
import { getRequestConfig } from 'next-intl/server';

import { defaultLocale, DISPLAY_TIME_ZONE, routing } from '@/i18n/routing';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : defaultLocale;

  return {
    locale,
    messages: (await import(`@/i18n/messages/${locale}.json`)).default,
    timeZone: DISPLAY_TIME_ZONE,
    now: new Date(),
  };
});
