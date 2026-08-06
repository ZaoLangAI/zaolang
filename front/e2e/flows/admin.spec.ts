import { expect, test } from '@playwright/test';

import { ACCOUNTS, SEED_PASSWORD, STATE_FILES, watchForPageErrors } from '../support/session';

/**
 * The operations console walkthrough: the separate admin session, then the
 * screens an operator actually opens during an incident.
 *
 * The seed script plants a wedged job, an overdue reservation, a pending data
 * request and a degraded agent run precisely so these assertions have something
 * to find; an empty console would let a broken query pass unnoticed.
 */

test.describe('session boundary', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the console sends an anonymous visitor to its own login page', async ({ page }) => {
    await page.goto('/zh-CN/admin/jobs', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL(/\/admin\/login/);
    await expect(page.getByRole('heading', { name: '运维台登录' })).toBeVisible();
  });

  test('a wrong password is rejected', async ({ page }) => {
    await page.goto('/zh-CN/admin/login', { waitUntil: 'networkidle' });
    await page.getByLabel('邮箱').fill(ACCOUNTS.admin);
    await page.getByLabel('密码').fill('definitely-not-the-password');
    await page.getByRole('button', { name: '进入运维台' }).click();

    await expect(page).toHaveURL(/\/admin\/login/);
    // One message for a wrong password and for a valid account without console
    // access, so the form cannot be used to enumerate operators.
    await expect(page.getByRole('alert').filter({ hasText: '邮箱或密码不正确' })).toBeVisible();
  });
});

test.describe('a consumer session is not a console session', () => {
  test.use({ storageState: STATE_FILES.consumer });

  test('the console still demands its own login', async ({ page }) => {
    // The consumer login set `zl_refresh`, not `zl_admin_session`.
    await page.goto('/zh-CN/admin/jobs', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL(/\/admin\/login/);
  });
});

test.describe('operations screens', () => {
  test.use({ storageState: STATE_FILES.admin });

  test('system health reports every dependency', async ({ page }) => {
    const problems = watchForPageErrors(page);
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });

    for (const service of ['postgres', 'redis', 'minio', 'celery']) {
      await expect(page.getByText(service, { exact: true })).toBeVisible();
    }
    expect(problems(), 'console errors on the health page').toEqual([]);
  });

  test('the job console lists the seeded jobs', async ({ page }) => {
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: '任务运维' }).click();
    await expect(page.getByRole('heading', { name: '任务运维', level: 1 })).toBeVisible();

    // Job ids are what an operator pastes in from an alert, so they belong on
    // screen rather than behind a hover.
    await expect(page.getByText(/^job_/).first()).toBeVisible();
  });

  test('the credits console surfaces the overdue reservation', async ({ page }) => {
    await page.goto('/zh-CN/admin/credits', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '积分运维', level: 1 })).toBeVisible();

    // The seeded stuck job holds a reservation older than the report's grace
    // period, so this section must not be empty.
    await expect(page.getByRole('heading', { name: '悬挂预扣' })).toBeVisible();
    await expect(page.getByText(/^job_/).first()).toBeVisible();
  });

  test('the config console opens a key for editing', async ({ page }) => {
    await page.goto('/zh-CN/admin/config', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '配置中心', level: 1 })).toBeVisible();

    // Every hot reload of pricing and routing goes through this editor, so it
    // has to load a real value rather than an empty form.
    await expect(page.getByRole('button', { name: /pricing/ }).first()).toBeVisible();
    await page
      .getByRole('button', { name: /pricing/ })
      .first()
      .click();
    await expect(page.getByRole('textbox').first()).not.toBeEmpty();
  });

  test('the log centre renders its table', async ({ page }) => {
    await page.goto('/zh-CN/admin/audit', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '日志中心', level: 1 })).toBeVisible();
    await expect(page.getByRole('table').first()).toBeVisible();
  });

  test('moderation and reports both have real queues', async ({ page }) => {
    await page.goto('/zh-CN/admin/moderation', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '内容审核', level: 1 })).toBeVisible();
    await expect(page.getByText('Night Tide · Neon').first()).toBeVisible();

    await page.goto('/zh-CN/admin/reports', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '举报与申诉', level: 1 })).toBeVisible();
    await expect(page.getByRole('table').first()).toBeVisible();
  });

  test('the user console finds the suspended seed account', async ({ page }) => {
    await page.goto('/zh-CN/admin/users', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '用户与权限', level: 1 })).toBeVisible();
    await expect(page.getByText(ACCOUNTS.suspended)).toBeVisible();
  });

  test('the agent console reports token spend and degradations', async ({ page }) => {
    await page.goto('/zh-CN/admin/agents', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '智能体运维', level: 1 })).toBeVisible();
    // Among the seeded runs is a Copy Agent call that fell back to the stub.
    await expect(page.getByText('copy').first()).toBeVisible();
  });

  test('the providers console renders the general/media tree', async ({ page }) => {
    await page.goto('/zh-CN/admin/providers', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '模型提供方配置', level: 1 })).toBeVisible();

    // One flat "general models" section plus one "media models" branch with
    // all six capability tags — present even before any media endpoint has
    // been configured, since the tree itself is a fixed taxonomy.
    await expect(page.getByRole('heading', { name: '通用模型' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '媒体模型' })).toBeVisible();
    for (const capability of ['文生图', '图生图', '文生视频', '图生视频', '视频生视频', '音频生成']) {
      await expect(page.getByRole('heading', { name: capability })).toBeVisible();
    }

    await page.getByRole('button', { name: '新增模型提供方' }).click();
    await expect(page.getByRole('heading', { name: '新增端点' })).toBeVisible();
    // Switching to a media provider swaps the single models field for the
    // per-capability checklist, which is the whole point of this rewrite.
    await page.getByLabel('模型类型').selectOption('media');
    await expect(page.getByText('媒体能力')).toBeVisible();
  });
});

test.describe('reviewer navigation', () => {
  test.use({ storageState: STATE_FILES.reviewer });

  test('a reviewer sees the review screens but not the platform ones', async ({ page }) => {
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });
    const nav = page.getByRole('navigation', { name: '造浪运维台' });

    await expect(nav.getByRole('link', { name: '内容审核' })).toBeVisible();
    // Trimming the navigation is a courtesy; the server enforces the same rule
    // regardless of what the client renders, which the API tests cover.
    await expect(nav.getByRole('link', { name: '配置中心' })).toBeHidden();
    await expect(nav.getByRole('link', { name: '数据运维' })).toBeHidden();
  });
});

test.describe('operator navigation', () => {
  test.use({ storageState: STATE_FILES.operator });

  test('an operator sees job and credit operations', async ({ page }) => {
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });
    const nav = page.getByRole('navigation', { name: '造浪运维台' });

    await expect(nav.getByRole('link', { name: '任务运维' })).toBeVisible();
    await expect(nav.getByRole('link', { name: '积分运维' })).toBeVisible();
    await expect(nav.getByRole('link', { name: '数据运维' })).toBeVisible();
  });

  test('an operator can read the config but not change it', async ({ page }) => {
    // Reading configuration is viewer-level; only an admin may write it, so the
    // page opens without offering a way to save.
    await page.goto('/zh-CN/admin/config', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '配置中心', level: 1 })).toBeVisible();
    await expect(page.getByRole('button', { name: '保存' })).toHaveCount(0);
  });
});

test.describe('unused seed credentials', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the suspended account cannot sign in to the console', async ({ page }) => {
    await page.goto('/zh-CN/admin/login', { waitUntil: 'networkidle' });
    await page.getByLabel('邮箱').fill(ACCOUNTS.suspended);
    await page.getByLabel('密码').fill(SEED_PASSWORD);
    await page.getByRole('button', { name: '进入运维台' }).click();

    await expect(page).toHaveURL(/\/admin\/login/);
    await expect(page.getByRole('alert').filter({ hasText: '邮箱或密码不正确' })).toBeVisible();
  });
});
