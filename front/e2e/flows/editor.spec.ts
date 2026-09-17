import { expect, test } from '@playwright/test';

import { STATE_FILES } from '../support/session';

/**
 * Desktop-only. The editor is gated off phones on purpose and is not in the
 * a11y-mobile scan list.
 */
test.describe('drama editor', () => {
  test.use({ storageState: STATE_FILES.consumer });

  test('the dashboard explains drama-series management', async ({ page }) => {
    await page.goto('/zh-CN/create/short', { waitUntil: 'load' });
    await expect(page.getByRole('heading', { name: '剧集管理' })).toBeVisible();
  });

  test('independent engines and a 10s chrome encode', async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto('/zh-CN/create/short/gold-sample', { waitUntil: 'load' });
    await expect(page.getByTestId('editor-engines')).toHaveAttribute('data-ok', 'true');
    await page.getByRole('button', { name: '导出 10 秒金样' }).click();
    await expect(page.getByTestId('editor-gold-sample')).toBeVisible({ timeout: 90_000 });
    const bytes = Number(await page.getByTestId('editor-gold-sample').getAttribute('data-bytes'));
    expect(bytes).toBeGreaterThan(1_000);
  });
});
