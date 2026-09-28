import { api, getAccessToken } from '@/lib/api/client';
import type { ThemePreference } from '@/lib/theme';

/**
 * The console route group, matched against the locale-less pathname from
 * `@/i18n/navigation`. Anchored so a consumer page such as `/profile/admin`
 * (a user whose handle is "admin") still syncs.
 */
const ADMIN_PATH = /^\/admin(?:\/|$)/;

/**
 * Stores the theme choice on the account so it follows the user to another
 * device; the cookie written by `ThemeProvider` already covers this device.
 *
 * `PATCH /v1/auth/me/preferences` requires a signed-in user, so the request
 * goes out authenticated and only when an access token is in memory. Signed
 * out, there is nothing to sync and no reason to spend a request on a 401.
 * An expired token takes the client's normal refresh-and-retry path.
 *
 * Console routes never write consumer preferences: the admin session is a
 * separate cookie, and a 401 here would redeem the consumer `/v1/auth/refresh`.
 *
 * A failed write is not worth interrupting the user over.
 */
export function syncThemePreference(theme: ThemePreference, pathname: string): void {
  if (ADMIN_PATH.test(pathname)) return;
  if (!getAccessToken()) return;
  void api.patch('/v1/auth/me/preferences', { theme }).catch(() => undefined);
}
