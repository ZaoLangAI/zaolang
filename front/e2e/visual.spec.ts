import { expect, test } from '@playwright/test';

import { expectNoHorizontalOverflow } from './support/axe';
import { watchForPageErrors } from './support/session';
import { expectTheme, setTheme } from './support/theme';

/**
 * Dark and light across the three design breakpoints.
 *
 * Screenshots are attached to the report for human review only. What this suite
 * decides on its own is mechanical and still worth failing on: nothing overflows
 * horizontally, and no page logs an error while rendering.
 */

const VIEWPORTS = [
  { label: 'desktop', width: 1440, height: 1024 },
  { label: 'tablet', width: 1024, height: 768 },
  { label: 'mobile', width: 390, height: 844 },
] as const;

const PAGES = [
  { path: '/zh-CN/discover', label: 'discover' },
  { path: '/zh-CN/learn', label: 'learn' },
  { path: '/zh-CN/create', label: 'create' },
  { path: '/zh-CN/admin/login', label: 'admin-login' },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const viewport of VIEWPORTS) {
    test.describe(`${theme} · ${viewport.label}`, () => {
      for (const target of PAGES) {
        test(`${target.label} renders without overflow`, async ({ page }, info) => {
          const problems = watchForPageErrors(page);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await setTheme(page, theme);
          await page.goto(target.path, { waitUntil: 'networkidle' });
          await expectTheme(page, theme);

          await expectNoHorizontalOverflow(page);

          await info.attach(`${target.label}-${theme}-${viewport.label}.png`, {
            body: await page.screenshot({ fullPage: true }),
            contentType: 'image/png',
          });

          expect(problems(), `console errors on ${target.label}`).toEqual([]);
        });
      }
    });
  }
}

test.describe('reduced motion', () => {
  test('animations are suppressed when the user asks for it', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });

    // Every animated element must resolve to an effectively instant duration;
    // a leftover long transition is what makes reduced-motion users seasick.
    const longAnimations = await page.evaluate(() => {
      const offenders: string[] = [];
      for (const element of Array.from(document.querySelectorAll('*'))) {
        const style = getComputedStyle(element);
        const durations = [style.transitionDuration, style.animationDuration]
          .join(',')
          .split(',')
          .map((value) => Number.parseFloat(value) || 0);
        if (durations.some((duration) => duration > 0.05)) {
          offenders.push(element.tagName.toLowerCase());
        }
      }
      return offenders.slice(0, 10);
    });

    expect(longAnimations).toEqual([]);
  });
});
