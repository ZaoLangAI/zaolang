import { test } from '@playwright/test';

import { expectNoAxeViolations, expectNoHorizontalOverflow } from './support/axe';
import { setTheme } from './support/theme';

/** Pages reachable without a session, in both themes. */
const PUBLIC_PAGES = [
  { path: '/zh-CN/discover', label: 'discover' },
  { path: '/zh-CN/learn', label: 'learn' },
  { path: '/zh-CN/create', label: 'create' },
  { path: '/zh-CN/admin/login', label: 'admin-login' },
];

for (const theme of ['dark', 'light'] as const) {
  test.describe(`${theme} theme`, () => {
    for (const page of PUBLIC_PAGES) {
      test(`${page.label} has no accessibility violations`, async ({ page: browserPage }, info) => {
        await setTheme(browserPage, theme);
        await browserPage.goto(page.path, { waitUntil: 'networkidle' });
        await expectNoAxeViolations(browserPage, info, `${page.label}-${theme}`);
        await expectNoHorizontalOverflow(browserPage);
      });
    }
  });
}

test('the command palette is reachable and labelled', async ({ page }, info) => {
  await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
  await page.keyboard.press('Meta+k');
  // The palette is a combobox with a listbox, per the ARIA pattern — not a
  // dialog, so waiting for one would time out.
  await page.getByRole('combobox', { name: '搜索页面、作品或操作' }).waitFor();
  await expectNoAxeViolations(page, info, 'command-palette');
});
