import { expect, test } from '@playwright/test';

import { ACCOUNTS, STATE_FILES, signInThroughDialog, watchForPageErrors } from '../support/session';
import { expectTheme, setTheme } from '../support/theme';

/**
 * The consumer journey from the acceptance list: browse, hit the login wall on a
 * protected action, come back to that action, then start a generation.
 *
 * Assertions go through what a user can see, so a refactor that preserves the
 * behaviour preserves the test.
 */

test.describe('anonymous browsing', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a visitor can browse the feed and open a work', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });

    // The seeded chain puts a root work and its remix in the public feed.
    await expect(page.getByRole('link', { name: '潮汐之上', exact: true }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: '潮汐之上 · 夜行' }).first()).toBeVisible();

    await page.getByRole('link', { name: '潮汐之上', exact: true }).first().click();
    await expect(page).toHaveURL(/\/work\/wrk_/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    expect(problems(), 'console errors while browsing').toEqual([]);
  });

  test('the withdrawn work is not in the feed', async ({ page }) => {
    // Its lineage edge survives as a tombstone, but the work itself is private.
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
    await expect(page.getByRole('link', { name: 'Night Tide (withdrawn)' })).toHaveCount(0);
  });

  test('a protected action opens the login wall and resumes afterwards', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: '潮汐之上', exact: true }).first().click();
    await expect(page).toHaveURL(/\/work\/wrk_/);

    await page.getByRole('button', { name: '点赞', exact: true }).click();

    // The dialog names the action it interrupted, which is what makes the
    // resumption comprehensible instead of surprising.
    await expect(page.getByRole('dialog')).toContainText('点赞');

    await signInThroughDialog(page, ACCOUNTS.author);

    // The interrupted like is replayed, so the button comes back pressed
    // without the user clicking a second time.
    await expect(page.getByRole('button', { name: '已点赞' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  test('cancelling the login wall abandons the action', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: '潮汐之上', exact: true }).first().click();

    await page.getByRole('button', { name: '收藏', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '取消' }).click();

    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByRole('button', { name: '收藏', exact: true })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});

test.describe('creation', () => {
  test.use({ storageState: STATE_FILES.consumer });

  test('a signed-in user can submit a generation and watch the job', async ({ page }) => {
    await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'networkidle' });

    await page.getByLabel('说说你想怎么改').fill('雨夜霓虹下的长镜头推进');
    // The radios are visually replaced by styled labels, so the label is what a
    // user clicks and therefore what the test clicks.
    await page.getByRole('radiogroup', { name: '质量档位' }).getByText('快速预览').click();
    await expect(page.getByRole('radio', { name: '快速预览' })).toBeChecked();

    await page.getByRole('checkbox').first().check();
    await page.getByRole('button', { name: '生成我的版本' }).click();

    // Submission lands on the job page, which streams progress over SSE.
    await expect(page).toHaveURL(/\/jobs\/job_/, { timeout: 30_000 });
    await expect(page.getByRole('heading', { name: '生成任务' })).toBeVisible();
    await expect(page.getByRole('progressbar')).toBeVisible();
  });

  test('the library shows the seeded draft awaiting publication', async ({ page }) => {
    await page.goto('/zh-CN/collection', { waitUntil: 'networkidle' });
    await expect(page.getByText('潮汐之上 · 未完成').first()).toBeVisible();
  });
});

test.describe('theme', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the chosen theme survives a reload without a flash of the other one', async ({ page }) => {
    await setTheme(page, 'light');
    // Asserted before network idle: the server must have rendered the attribute,
    // rather than the client patching it after hydration.
    await page.goto('/zh-CN/discover', { waitUntil: 'domcontentloaded' });
    await expectTheme(page, 'light');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expectTheme(page, 'light');
  });

  test('switching to dark from the preference menu persists', async ({ page }) => {
    await setTheme(page, 'light');
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });

    await page.locator('button[aria-haspopup="menu"]').first().click();
    await page.getByRole('menuitemradio', { name: '深色' }).click();
    await expectTheme(page, 'dark');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expectTheme(page, 'dark');
  });
});

test.describe('command palette', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('Cmd+K opens a labelled combobox and searches', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });

    await page.keyboard.press('Meta+k');
    const input = page.getByRole('combobox', { name: '搜索页面、作品或操作' });
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute('aria-expanded', 'true');

    // With a query typed, the first option is the search itself, so Enter runs
    // the search rather than jumping to a page.
    await input.fill('潮汐');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/discover\?q=/);
  });

  test('the palette navigates to a page by name', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
    await page.keyboard.press('Meta+k');

    await page.getByRole('option', { name: '学习' }).click();
    await expect(page).toHaveURL(/\/learn/);
  });
});
