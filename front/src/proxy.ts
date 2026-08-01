import createMiddleware from 'next-intl/middleware';

import { routing } from '@/i18n/routing';

/**
 * Next 16 renamed the middleware convention to `proxy`. The handler still does
 * one job: resolve the locale prefix so `<html lang>` and every `Link` agree
 * on which of the three languages the request is for.
 */
export default createMiddleware(routing);

export const config = {
  // Everything except Next internals and files with an extension, which are
  // static assets and must not be locale-prefixed.
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
