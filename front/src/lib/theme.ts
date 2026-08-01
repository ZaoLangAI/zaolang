export const themePreferences = ['system', 'dark', 'light'] as const;
export type ThemePreference = (typeof themePreferences)[number];

/** What actually ends up on `<html data-theme>`. */
export type ResolvedTheme = 'dark' | 'light';

export const THEME_COOKIE = 'zl_theme';
export const MOTION_COOKIE = 'zl_reduce_motion';

/** Dark is the design baseline, so it is also the fallback for `system`. */
export const defaultTheme: ThemePreference = 'system';

export function isThemePreference(value: string | undefined): value is ThemePreference {
  return !!value && (themePreferences as readonly string[]).includes(value);
}

/**
 * Browser chrome colour per theme.
 *
 * Mobile Safari paints the notch area with this; leaving it stale makes a
 * light page sit under a black bar.
 */
export const themeColor: Record<ResolvedTheme, string> = {
  dark: '#080b0d',
  light: '#f7f4f0',
};

/**
 * Inlined into `<head>` before first paint.
 *
 * The server renders `data-theme` from the cookie, which covers `dark` and
 * `light` with no flash. `system` is the one case the server cannot resolve —
 * it depends on the OS setting — so this script fixes it up synchronously,
 * before the browser has painted anything.
 */
export const themeInitScript = `
(function () {
  try {
    var root = document.documentElement;
    var pref = root.dataset.themePreference || 'system';
    if (pref !== 'system') return;
    var dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = dark ? 'dark' : 'light';
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'dark' ? '${themeColor.dark}' : '${themeColor.light}');
  } catch (e) {}
})();
`.trim();

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light';
  return preference;
}
