import { test } from '@playwright/test';

import { expectNoAxeViolations, expectNoHorizontalOverflow } from './support/axe';
import { STATE_FILES } from './support/session';
import { setTheme } from './support/theme';

/**
 * Run twice by the `a11y` and `a11y-mobile` projects, at 1440×1024 and
 * 390×844. The narrow pass is not redundant: the phone layouts move controls
 * into sheets and fixed bars, and those are exactly the constructs that lose a
 * label or trap focus.
 */

/** Pages reachable without a session, in both themes. */
const PUBLIC_PAGES = [
  { path: '/zh-CN/discover', label: 'discover' },
  { path: '/zh-CN/learn', label: 'learn' },
  { path: '/zh-CN/create', label: 'create' },
  { path: '/zh-CN/create/short', label: 'create-short' },
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

test.describe('generation studio (signed in)', () => {
  test.use({ storageState: STATE_FILES.consumer });

  test('the style gallery dialog and more-settings panel have no violations', async ({
    page,
  }, info) => {
    await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'networkidle' });
    await expectNoAxeViolations(page, info, 'generation-studio');
    await expectNoHorizontalOverflow(page);

    // Below the `lg` breakpoint the params panel — including the style gallery
    // trigger and the more-settings toggle — lives inside a sheet opened from
    // the fixed bottom bar, rather than the aside rendered on wide viewports.
    const styleTrigger = page.getByRole('button', { name: '选择系统画风' });
    if (!(await styleTrigger.isVisible())) {
      await page.getByRole('button', { name: '参数', exact: true }).click();
    }

    await styleTrigger.click();
    // Named explicitly: on narrow viewports the params sheet underneath is
    // itself a `role="dialog"`, so an unscoped lookup is ambiguous.
    const dialog = page.getByRole('dialog', { name: '系统画风库' });
    await dialog.waitFor();
    // The dialog fades and scales in over 220ms; axe would otherwise sample
    // colours mid-transition and report a false contrast violation.
    await page.waitForTimeout(300);
    await expectNoAxeViolations(page, info, 'generation-studio-style-gallery');
    // Axe's own DOM probing can leave focus outside the dialog, and Escape
    // only reaches the panel's own key handler while it holds focus.
    await dialog.focus();
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });

    await page.getByRole('button', { name: '更多设置' }).click();
    await expectNoAxeViolations(page, info, 'generation-studio-more-settings');
  });
});
