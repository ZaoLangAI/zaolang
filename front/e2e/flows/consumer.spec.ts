import { expect, test, type Page } from '@playwright/test';

import { FIXTURE_TITLES, fixtures } from '../support/fixtures';
import { ACCOUNTS, STATE_FILES, signInThroughDialog, watchForPageErrors } from '../support/session';
import { expectTheme, setTheme } from '../support/theme';

/**
 * The consumer journey from the acceptance list: browse, hit the login wall on a
 * protected action, come back to that action, then start a generation.
 *
 * Assertions go through what a user can see, so a refactor that preserves the
 * behaviour preserves the test.
 *
 * Navigations wait for `load`, not `networkidle`: the site shell holds the
 * notification SSE open when signed in, and Discover's hero may keep a
 * video buffer in flight. Either connection makes Playwright's idle wait
 * hang for the full test timeout even though the page is already usable.
 */

/**
 * Opens a fixture work's page directly. Search tiles are not used here: a
 * narrow query puts the hit in the hero and slices it off the wall, so the
 * preview button is often not in the DOM.
 */
async function openPublicWork(page: Page, workId: string) {
  await page.goto(`/zh-CN/work/${workId}`, { waitUntil: 'load' });
  await expect(page).toHaveURL(/\/work\/wrk_/);
}

test.describe('anonymous browsing', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a visitor can browse the feed and open a work', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await page.goto(`/zh-CN/discover?q=${encodeURIComponent(FIXTURE_TITLES.freeRemix)}`, {
      waitUntil: 'load',
    });

    await expect(page.getByText(FIXTURE_TITLES.freeRemix).first()).toBeVisible();

    await openPublicWork(page, fixtures().free_remix_work_id);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    expect(problems(), 'console errors while browsing').toEqual([]);
  });

  test('the inspiration wall can be sorted by recency', async ({ page }) => {
    // Needs published works, or the feed renders its empty state instead of
    // a list; `make e2e-fixtures` provides them.
    fixtures();
    await page.goto('/zh-CN/discover', { waitUntil: 'load' });
    await page
      .getByRole('navigation', { name: '排序' })
      .getByRole('link', { name: '最新' })
      .click();
    await expect(page).toHaveURL(/sort=recent/);
    await expect(page.getByRole('list', { name: '灵感推荐' })).toBeVisible();
  });

  test('the withdrawn work is not in the feed', async ({ page }) => {
    fixtures();
    // Searched by name, so a leak would show up rather than being buried under
    // the popular sort. The title still appears as the tombstone in its remix's
    // lineage — that is the point of a tombstone — so the assertion is about the
    // wall, not about the string being absent from the page.
    await page.goto('/zh-CN/discover?q=Night Tide', { waitUntil: 'load' });
    // The withdrawn work's own remix is still public and matches the same
    // query. Seeing it first proves the wall rendered results, so the absence
    // below cannot pass on an empty page.
    await expect(page.getByText(FIXTURE_TITLES.deepRemix).first()).toBeVisible();
    await expect(
      page.getByRole('button', { name: `预览《${FIXTURE_TITLES.withdrawn}》`, exact: true }),
    ).toHaveCount(0);
  });

  test('a protected action opens the login wall and resumes afterwards', async ({ page }) => {
    // `make e2e-fixtures` clears the author's like on this work each run, so
    // the button starts unpressed.
    await openPublicWork(page, fixtures().free_remix_work_id);

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
    await openPublicWork(page, fixtures().free_remix_work_id);

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

  test('a signed-in user can configure an H3 video generation', async ({ page }) => {
    await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'load' });

    await page.getByLabel('说说你想怎么改').fill('雨夜霓虹下的长镜头推进');
    // Resolution is a client tier the router maps to each vendor's spelling,
    // so it is always pickable; 1080p is the studio's own default.
    await expect(page.getByLabel('分辨率')).toHaveValue('1080p');
    await page.getByLabel('分辨率').selectOption('2K');
    await expect(page.getByLabel('分辨率')).toHaveValue('2K');
    // The seed lives in the collapsed "更多设置" section.
    await page.getByRole('button', { name: '更多设置' }).click();
    await page.getByLabel('随机种子').fill('42');
    await page.getByRole('radiogroup', { name: '时长' }).getByText('15 秒').click();
    await page.getByRole('radiogroup', { name: '画面方向' }).getByText('横屏').click();
    await page.getByRole('radiogroup', { name: '画幅' }).getByText('21:9').click();
    // Reference mode lives in its own collapsed "参考设置" section.
    await page.getByRole('button', { name: '参考设置' }).click();
    await page.getByRole('radiogroup', { name: '参考方式' }).getByText('首尾帧').click();
    await expect(page.getByLabel('首帧')).toBeVisible();
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeDisabled();
    await page.getByRole('radiogroup', { name: '参考方式' }).getByText('图片/视频参考').click();
    await expect(page.locator('input[type="file"]')).toHaveAttribute('accept', /video\/mp4/);
    // The radios are visually replaced by styled labels, so the label is what a
    // user clicks and therefore what the test clicks.
    await page.getByRole('radiogroup', { name: '质量档位' }).getByText('快速预览').click();
    await expect(page.getByRole('radio', { name: '快速预览' })).toBeChecked();

    // By name: the portrait-consent checkbox in the sources panel comes first.
    await page.getByRole('checkbox', { name: /我确认拥有新增素材的使用权/ }).check();
    // This suite may run against a developer's live provider configuration.
    // Stop before submission so UI coverage never creates a billable render;
    // backend lifecycle tests exercise submit -> SSE -> terminal settlement.
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeEnabled();
  });

  test('a signed-in user can open the text-to-image studio', async ({ page }) => {
    await page.goto('/zh-CN/create/new?mode=image_creation', { waitUntil: 'load' });
    await expect(page.getByRole('heading', { name: '图片创作' })).toBeVisible();
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeVisible();

    // Polishing used to be video-only; an image prompt needs the same help.
    // Not clicked — that would spend a real model call, same discipline as
    // the submit buttons above.
    await page.getByLabel('说说你想怎么改').fill('女孩在海边');
    await expect(page.getByRole('button', { name: 'AI 润色' })).toBeEnabled();
  });

  test('a new character lands on its own management page and back', async ({ page }) => {
    const name = `E2E角色${Date.now().toString(36)}`;
    await page.goto('/zh-CN/create/characters', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建角色' }).first().click();
    await page.getByLabel('角色名称').fill(name);
    // The edit dialog is text-only now: no 角色设定图 slot to fill.
    await expect(page.getByText('角色设定图')).toHaveCount(0);
    await page.getByRole('button', { name: '保存并管理造型' }).click();

    await expect(page).toHaveURL(/\/create\/characters\/sk_[^/?]+$/);
    await expect(page.getByRole('heading', { name })).toBeVisible();
    const cardUrl = page.url();
    const cardId = cardUrl.split('/').pop() ?? '';

    // A pre-page 去定稿 link (`?manage=`) still lands on the card.
    await page.goto(`/zh-CN/create/characters?manage=${cardId}`, { waitUntil: 'load' });
    await expect(page).toHaveURL(cardUrl);

    await page.getByRole('link', { name: '返回角色库' }).click();
    await expect(page).toHaveURL(/\/create\/characters$/);
    await expect(page.getByRole('heading', { name, level: 3 })).toBeVisible();
  });

  test('the library shows the fixture draft awaiting publication', async ({ page }) => {
    fixtures();
    await page.goto('/zh-CN/collection', { waitUntil: 'load' });
    await expect(page.getByText(FIXTURE_TITLES.draft).first()).toBeVisible();
  });

  test('a paid remixable work can be unlocked and then remixed', async ({ page }) => {
    const problems = watchForPageErrors(page);
    // A purchase is permanent, so `make e2e-fixtures` withdraws a paid work
    // this account already bought and publishes a fresh one (the manifest
    // points at it) and tops the balance back up — the paywall is there every run.
    await openPublicWork(page, fixtures().paid_work_id);
    await expect(page.getByText('10 积分').first()).toBeVisible();

    await page.getByRole('button', { name: '积分解锁并二创' }).click();
    const unlock = page.getByRole('dialog');
    await expect(unlock).toContainText('积分解锁');
    await unlock.getByRole('button', { name: '积分解锁' }).click();
    await expect(page).toHaveURL(/\/remix\/wrk_/);
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeVisible();
    expect(problems(), 'console errors while unlocking a paid work').toEqual([]);
  });

  test('a locked paid skill cannot be applied without unlocking', async ({ page }) => {
    fixtures();
    await page.goto('/zh-CN/skills?access=paid', { waitUntil: 'load' });
    await expect(page.getByRole('heading', { name: FIXTURE_TITLES.paidSkill })).toBeVisible();
    await expect(page.getByText('8 积分').first()).toBeVisible();

    // Image and video apply skills through the prompt `@` menu; the audio
    // studio is the one that still offers the creation-skill Select.
    await page.goto('/zh-CN/create/new?mode=audio_generation', { waitUntil: 'load' });
    await page
      .getByLabel('创作技能')
      .selectOption({ label: `${FIXTURE_TITLES.paidSkill} · 8 积分` });
    const unlock = page.getByRole('dialog');
    await expect(unlock).toContainText('积分解锁');
    await unlock.getByRole('button', { name: '取消' }).click();
    await expect(page.getByLabel('说说你想怎么改')).not.toHaveValue(/golden hour/);
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

  test('switching to dark from the theme menu persists', async ({ page }) => {
    await setTheme(page, 'light');
    await page.goto('/zh-CN/discover', { waitUntil: 'load' });

    // Theme has its own menu now, so it is addressed by name rather than by
    // being the only popover in the top bar.
    await page.getByRole('button', { name: '切换主题' }).first().click();
    await page.getByRole('menuitemradio', { name: '深色' }).click();
    await expectTheme(page, 'dark');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expectTheme(page, 'dark');
  });
});

test.describe('command palette', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('Cmd+K opens a labelled combobox and searches', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'load' });

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
    await page.goto('/zh-CN/discover', { waitUntil: 'load' });
    await page.keyboard.press('Meta+k');
    await expect(page.getByRole('combobox', { name: '搜索页面、作品或操作' })).toBeVisible();

    await page.getByRole('option', { name: '学习', exact: true }).click();
    await expect(page).toHaveURL(/\/learn/);
  });
});
