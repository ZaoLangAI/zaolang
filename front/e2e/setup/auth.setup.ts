import { expect, test as setup } from '@playwright/test';

import { ACCOUNTS, SEED_PASSWORD, STATE_FILES } from '../support/session';

/**
 * Signs in once per role and saves the cookies for the suites to reuse.
 *
 * This is not only about speed. `/v1/auth/login` is rate limited to ten attempts
 * per five minutes per address, which is correct product behaviour and which a
 * suite that logged in for every test would trip — turning a real protection
 * into a flaky failure. Logging in four times up front keeps the whole run well
 * inside the budget, and the tests that are specifically *about* logging in
 * still do it for real.
 */

setup('sign in as the console admin', async ({ page }) => {
  await page.goto('/zh-CN/admin/login');
  await page.getByLabel('邮箱').fill(ACCOUNTS.admin);
  await page.getByLabel('密码').fill(SEED_PASSWORD);
  await page.getByRole('button', { name: '进入运维台' }).click();
  await expect(page.getByRole('navigation', { name: '造浪运维台' })).toBeVisible();
  await page.context().storageState({ path: STATE_FILES.admin });
});

setup('sign in as a reviewer', async ({ page }) => {
  await page.goto('/zh-CN/admin/login');
  await page.getByLabel('邮箱').fill(ACCOUNTS.reviewer);
  await page.getByLabel('密码').fill(SEED_PASSWORD);
  await page.getByRole('button', { name: '进入运维台' }).click();
  await expect(page.getByRole('navigation', { name: '造浪运维台' })).toBeVisible();
  await page.context().storageState({ path: STATE_FILES.reviewer });
});

setup('sign in as an operator', async ({ page }) => {
  await page.goto('/zh-CN/admin/login');
  await page.getByLabel('邮箱').fill(ACCOUNTS.operator);
  await page.getByLabel('密码').fill(SEED_PASSWORD);
  await page.getByRole('button', { name: '进入运维台' }).click();
  await expect(page.getByRole('navigation', { name: '造浪运维台' })).toBeVisible();
  await page.context().storageState({ path: STATE_FILES.operator });
});

setup('sign in as a consumer', async ({ page }) => {
  await page.goto('/zh-CN/discover');
  await page.getByRole('button', { name: '登录', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('邮箱').fill(ACCOUNTS.remixer);
  await dialog.getByLabel('密码').fill(SEED_PASSWORD);
  await dialog.getByRole('button', { name: '登录', exact: true }).click();
  await expect(dialog).toBeHidden();
  // The access token lives in memory only; what persists is the refresh cookie,
  // which is enough for the app to restore the session on the next load.
  await expect(page.getByRole('button', { name: '账号菜单' })).toBeVisible();
  await page.context().storageState({ path: STATE_FILES.consumer });
});
