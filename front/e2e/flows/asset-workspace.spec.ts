import { expect, test, type Page } from '@playwright/test';

import { STATE_FILES, watchForPageErrors } from '../support/session';

/**
 * 角色 / 场景 / 道具创作 (AC-5, AC-6): a library page is the starting point,
 * a new card lands on its workspace's 创作 tab, and a pose slot prices the
 * angles picked on its dial before anything is submitted.
 *
 * Nothing here generates: quotes are dry runs, so the flow needs the API and
 * the seed but no worker or image provider. Card names carry a timestamp —
 * character names are unique per owner and the seeded author keeps them
 * between runs.
 */

// A 1x1 PNG: enough for an upload to round-trip and be filed as the hero plate.
const DOT_PNG = {
  name: 'dot.png',
  mimeType: 'image/png',
  buffer: Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64',
  ),
};

function uniqueName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}`;
}

async function expectCreateTab(page: Page) {
  await expect(page.getByRole('tab', { name: '创作' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('region', { name: '资产板' })).toBeVisible();
}

test.describe('asset workspace', () => {
  test.use({ storageState: STATE_FILES.author });

  test('a character created from a description opens on its 创作 tab', async ({ page }) => {
    const problems = watchForPageErrors(page);
    const name = uniqueName('测试角色');
    await page.goto('/zh-CN/create/characters', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建角色' }).first().click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('角色名称').fill(name);
    await dialog.getByLabel('角色描述').fill('二十出头，短发，深色风衣');
    await dialog.getByRole('button', { name: '保存并管理造型' }).click();

    await expect(page).toHaveURL(/\/create\/characters\/sk_[^/?]+\?slot=portrait/);
    await expect(page.getByRole('heading', { name })).toBeVisible();
    await expectCreateTab(page);
    // No portrait yet, so the board opens on it.
    await expect(
      page.getByRole('region', { name: '资产板' }).getByRole('button', { name: /定妆照/ }),
    ).toHaveAttribute('aria-pressed', 'true');

    expect(problems(), 'console errors while creating a character').toEqual([]);
  });

  test('a prop created from a description opens its workspace', async ({ page }) => {
    const problems = watchForPageErrors(page);
    const name = uniqueName('测试道具');
    await page.goto('/zh-CN/create/props', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建道具' }).first().click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('道具名称').fill(name);
    await dialog.getByLabel('道具描述').fill('青铜材质，剑格嵌绿松石');
    await dialog.getByRole('button', { name: '创建并进入工作区' }).click();

    await expect(page).toHaveURL(/\/create\/props\/sk_[^/?]+\?slot=master/);
    await expect(page.getByRole('heading', { name })).toBeVisible();
    await expectCreateTab(page);
    await expect(page.getByRole('tab', { name: /状态图谱/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /音色/ })).toHaveCount(0);
    await expect(page.getByRole('complementary', { name: '生成面板' })).toContainText('积分');

    // The library lists it with its completeness badge.
    await page.getByRole('link', { name: '返回道具库' }).click();
    await expect(page.getByRole('heading', { name, level: 3 })).toBeVisible();

    expect(problems(), 'console errors while creating a prop').toEqual([]);
  });

  test('a pose slot quotes the angles picked on the dial', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await page.goto('/zh-CN/create/props', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建道具' }).first().click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('道具名称').fill(uniqueName('测试转台'));
    const uploaded = page.waitForResponse(
      (r) => r.url().includes('/v1/uploads/complete') && r.ok(),
      { timeout: 20_000 },
    );
    await dialog.locator('input[type="file"]').setInputFiles(DOT_PNG);
    await uploaded;
    await dialog.getByRole('button', { name: '创建并进入工作区' }).click();

    // The upload is the approved hero plate, so the board opens on the first
    // turntable angle, drawn from it.
    await expect(page).toHaveURL(/\/create\/props\/sk_[^/?]+\?slot=side/);
    const board = page.getByRole('region', { name: '资产板' });
    await expect(board.getByRole('button', { name: /主图/ })).toContainText('已定稿');

    await board.getByRole('button', { name: /背面 180°/ }).click();
    const panel = page.getByRole('complementary', { name: '生成面板' });
    const dial = panel.getByRole('group', { name: '机位方位（相对主体）' });
    await expect(dial).toBeVisible();
    await expect(dial.getByRole('button', { name: /背面 180°/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // The slot's own angle plus every other missing turntable pose, one
    // image each, priced by a dry run.
    const picked = panel.getByRole('list', { name: '已选机位' }).getByRole('listitem');
    await expect(picked).toHaveCount(4);
    const submit = panel.getByRole('button', { name: /生成（\d+ 积分）/ });
    const credits = async () => Number((await submit.innerText()).match(/(\d+) 积分/)?.[1]);
    await expect(submit).toBeEnabled();
    const four = await credits();

    await dial.getByRole('button', { name: /左侧 270°/ }).click();
    await expect(picked).toHaveCount(3);
    await expect.poll(credits).toBe((four / 4) * 3);
    await expect(submit).toBeEnabled();

    expect(problems(), 'console errors on the pose slot').toEqual([]);
  });
});
