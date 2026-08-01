import { expect, type Page } from '@playwright/test';

/**
 * Pins the theme through the same cookie the app reads during SSR.
 *
 * Setting the cookie rather than clicking the switcher means the very first
 * paint is already in the requested theme, which is what the no-flash guarantee
 * and the screenshot comparison both depend on. Scoped by domain rather than URL
 * so it does not care which port the run picked.
 */
export async function setTheme(page: Page, theme: 'dark' | 'light') {
  await page.context().addCookies([
    { name: 'zl_theme', value: theme, domain: '127.0.0.1', path: '/' },
    { name: 'zl_theme', value: theme, domain: 'localhost', path: '/' },
  ]);
}

/** Asserts the rendered theme matches what was asked for. */
export async function expectTheme(page: Page, theme: 'dark' | 'light') {
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}
