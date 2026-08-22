import { expect, test, type Page } from '@playwright/test';

import { ACCOUNTS, STATE_FILES, signInThroughDialog, watchForPageErrors } from '../support/session';
import { expectTheme, setTheme } from '../support/theme';

/**
 * The consumer journey from the acceptance list: browse, hit the login wall on a
 * protected action, come back to that action, then start a generation.
 *
 * Assertions go through what a user can see, so a refactor that preserves the
 * behaviour preserves the test.
 */

const API_URL = process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8000';

/** Active free remix in the seeded chain. The original root may be tombstoned. */
const SEEDED_FREE_REMIX = '潮汐之上 · 夜行';
const SEEDED_PAID_WORK = '潮汐之上 · 付费样例';
const SEEDED_PAID_SKILL = '黄金时刻镜头';

async function findPublicWorkId(page: Page, title: string): Promise<string> {
  const response = await page.request.get(`${API_URL}/v1/works`, {
    params: { q: title, limit: 40 },
  });
  const body = (await response.json()) as { items?: Array<{ id: string; title: string }> };
  const work = (body.items ?? []).find((item) => item.title === title);
  expect(work, `public work titled ${title}`).toBeTruthy();
  return work!.id;
}

/**
 * Opens a public work page. Search tiles are not used here: a narrow query
 * puts the hit in the hero and slices it off the wall, so the preview button
 * is often not in the DOM.
 */
async function openPublicWork(page: Page, title: string) {
  const id = await findPublicWorkId(page, title);
  await page.goto(`/zh-CN/work/${id}`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(/\/work\/wrk_/);
}

test.describe('anonymous browsing', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  // Skipped: `make seed` no longer publishes any work (see `back/app/scripts/seed.py`),
  // so there is nothing in the feed to find. Restore once a fixture-creation helper
  // can publish a real work for the suite to use.
  test.skip('a visitor can browse the feed and open a work', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await page.goto(`/zh-CN/discover?q=${encodeURIComponent(SEEDED_FREE_REMIX)}`, {
      waitUntil: 'networkidle',
    });

    await expect(page.getByText(SEEDED_FREE_REMIX).first()).toBeVisible();

    await openPublicWork(page, SEEDED_FREE_REMIX);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    expect(problems(), 'console errors while browsing').toEqual([]);
  });

  // Skipped: `make seed` no longer publishes any work, so the feed renders
  // its empty state (`discover.emptyFeed`) instead of a `role="list"`.
  // Restore once a fixture-creation helper can publish enough works to sort.
  test.skip('the inspiration wall can be sorted by recency', async ({ page }) => {
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });
    await page.getByRole('navigation', { name: '排序' }).getByRole('link', { name: '最新' }).click();
    await expect(page).toHaveURL(/sort=recent/);
    await expect(page.getByRole('list', { name: '灵感推荐' })).toBeVisible();
  });

  // Skipped: the tombstoned work in this scenario came from the seeded remix
  // chain, which `make seed` no longer creates. Restore once there is a real
  // tombstoned work to assert against.
  test.skip('the withdrawn work is not in the feed', async ({ page }) => {
    // Searched by name, so a leak would show up rather than being buried under
    // the popular sort. The title still appears as the tombstone in its remix's
    // lineage — that is the point of a tombstone — so the assertion is about the
    // wall, not about the string being absent from the page.
    await page.goto('/zh-CN/discover?q=Night Tide', { waitUntil: 'networkidle' });
    await expect(
      page.getByRole('button', { name: '预览《Night Tide (withdrawn)》', exact: true }),
    ).toHaveCount(0);
  });

  // Skipped: needs `SEEDED_FREE_REMIX` to exist as a public work, which
  // `make seed` no longer publishes. Restore once a fixture-creation helper
  // can publish one for the suite.
  test.skip('a protected action opens the login wall and resumes afterwards', async ({ page }) => {
    await openPublicWork(page, SEEDED_FREE_REMIX);

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

  // Skipped: needs `SEEDED_FREE_REMIX` to exist as a public work, which
  // `make seed` no longer publishes. Restore once a fixture-creation helper
  // can publish one for the suite.
  test.skip('cancelling the login wall abandons the action', async ({ page }) => {
    await openPublicWork(page, SEEDED_FREE_REMIX);

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
    await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'networkidle' });

    await page.getByLabel('说说你想怎么改').fill('雨夜霓虹下的长镜头推进');
    // Resolution and seed live in the collapsed "更多设置" section.
    await page.getByRole('button', { name: '更多设置' }).click();
    await expect(page.getByLabel('分辨率')).toHaveValue('2K');
    await expect(page.getByLabel('分辨率')).toBeDisabled();
    await page.getByLabel('随机种子').fill('42');
    await page.getByRole('radiogroup', { name: '时长' }).getByText('15 秒').click();
    await page.getByRole('radiogroup', { name: '画面方向' }).getByText('横屏').click();
    await page.getByRole('radiogroup', { name: '画幅' }).getByText('21:9').click();
    await page.getByRole('radiogroup', { name: '参考方式' }).getByText('首尾帧').click();
    await expect(page.getByLabel('首帧')).toBeVisible();
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeDisabled();
    await page.getByRole('radiogroup', { name: '参考方式' }).getByText('图片/视频参考').click();
    await expect(page.locator('input[type="file"]')).toHaveAttribute('accept', /video\/mp4/);
    // The radios are visually replaced by styled labels, so the label is what a
    // user clicks and therefore what the test clicks.
    await page.getByRole('radiogroup', { name: '质量档位' }).getByText('快速预览').click();
    await expect(page.getByRole('radio', { name: '快速预览' })).toBeChecked();

    await page.getByRole('checkbox').first().check();
    // This suite may run against a developer's live provider configuration.
    // Stop before submission so UI coverage never creates a billable render;
    // backend lifecycle tests exercise submit -> SSE -> terminal settlement.
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeEnabled();
  });

  test('a signed-in user can open the text-to-image studio', async ({ page }) => {
    await page.goto('/zh-CN/create/new?mode=image_creation', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '图片创作' })).toBeVisible();
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeVisible();

    // Polishing used to be video-only; an image prompt needs the same help.
    // Not clicked — that would spend a real model call, same discipline as
    // the submit buttons above.
    await page.getByLabel('说说你想怎么改').fill('女孩在海边');
    await expect(page.getByRole('button', { name: 'AI 润色' })).toBeEnabled();
  });

  // Skipped: this draft came from the seed's ops-material fixtures, which
  // `make seed` no longer creates. Restore once a fixture-creation helper can
  // leave a real draft behind.
  test.skip('the library shows the seeded draft awaiting publication', async ({ page }) => {
    await page.goto('/zh-CN/collection', { waitUntil: 'networkidle' });
    await expect(page.getByText('潮汐之上 · 未完成').first()).toBeVisible();
  });

  test('the shortform studio offers the clarify step and a preview-first submit', async ({
    page,
  }) => {
    await page.goto('/zh-CN/create/short', { waitUntil: 'networkidle' });

    await page.getByLabel('画面描述').fill('女孩在海边');

    // The clarify button sits next to the existing polish button rather than
    // replacing it — both must be reachable at once.
    await expect(page.getByRole('button', { name: 'AI 润色' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'AI 帮你补全细节' })).toBeVisible();

    // With the preview picker enabled, `preview` drops out of the tier choice
    // (it is no longer a submittable destination on its own) and the main CTA
    // becomes "生成预览" instead of "生成短视频". Not clicked — that would
    // spend real credits on live provider config, same discipline as the
    // H3 config test above.
    await expect(page.getByRole('radiogroup', { name: '质量档位' }).getByText('快速预览')).toHaveCount(0);
    await expect(page.getByRole('radiogroup', { name: '质量档位' }).getByText('标准')).toBeVisible();
    await expect(page.getByRole('button', { name: '生成预览' })).toBeVisible();
  });

  // Skipped: needs `SEEDED_PAID_WORK` to exist, which `make seed` no longer
  // publishes. Restore once a fixture-creation helper can publish a paid
  // remixable work for the suite.
  test.skip('a paid remixable work can be unlocked and then remixed', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await openPublicWork(page, SEEDED_PAID_WORK);
    await expect(page.getByText('10 积分').first()).toBeVisible();

    await page.getByRole('button', { name: '积分解锁并二创' }).click();
    const unlock = page.getByRole('dialog');
    await expect(unlock).toContainText('积分解锁');
    await unlock.getByRole('button', { name: '积分解锁' }).click();
    await expect(page).toHaveURL(/\/remix\/wrk_/);
    await expect(page.getByRole('button', { name: '生成我的版本' })).toBeVisible();
    expect(problems(), 'console errors while unlocking a paid work').toEqual([]);
  });

  // Skipped: needs `SEEDED_PAID_SKILL` to exist, which `make seed` no longer
  // publishes. Restore once a fixture-creation helper can publish a paid
  // creation skill for the suite.
  test.skip('a locked paid skill cannot be applied without unlocking', async ({ page }) => {
    await page.goto('/zh-CN/skills?access=paid', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: SEEDED_PAID_SKILL })).toBeVisible();
    await expect(page.getByText('8 积分').first()).toBeVisible();

    // The seeded paid skill is a `lens` (镜头) skill, and the creation-skill
    // picker (`useStyleAndSkillPicker`) only exists on the video/audio
    // studios — `ImageGenerationStudio` deliberately has no skill picker at
    // all — so this exercises the video studio, not the image one.
    await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'networkidle' });
    await page.getByLabel('创作技能').selectOption({ label: '黄金时刻镜头 · 8 积分' });
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
    await page.goto('/zh-CN/discover', { waitUntil: 'networkidle' });

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

    await page.getByRole('option', { name: '学习', exact: true }).click();
    await expect(page).toHaveURL(/\/learn/);
  });
});
