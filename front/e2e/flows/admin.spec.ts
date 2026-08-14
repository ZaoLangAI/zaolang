import { expect, test, type Page } from '@playwright/test';

import { ACCOUNTS, SEED_PASSWORD, STATE_FILES, watchForPageErrors } from '../support/session';

/** Consumer refresh must never fire on console routes. */
function watchConsumerRefresh(page: Page): () => string[] {
  const urls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/v1/auth/refresh')) urls.push(request.url());
  });
  return () => [...urls];
}

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

  test('a page that server-fetches console data still redirects instead of throwing', async ({
    page,
  }) => {
    // `/admin/config` calls `adminFetch` in the page RSC. Layout and page
    // render in parallel, so a 401 must redirect rather than surface as a
    // Runtime ApiError overlay.
    await page.goto('/zh-CN/admin/config', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL(/\/admin\/login/);
    await expect(page.getByRole('heading', { name: '运维台登录' })).toBeVisible();
    await expect(page.getByText('Runtime ApiError')).toHaveCount(0);
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

  test('console login never redeems a consumer refresh cookie', async ({ page }) => {
    const refreshCalls = watchConsumerRefresh(page);
    await page.goto('/zh-CN/admin/login', { waitUntil: 'networkidle' });
    await page.getByLabel('邮箱').fill(ACCOUNTS.admin);
    await page.getByLabel('密码').fill(SEED_PASSWORD);
    await page.getByRole('button', { name: '进入运维台' }).click();
    await expect(page).toHaveURL(/\/admin\/?$/);
    expect(refreshCalls(), 'consumer /v1/auth/refresh during console login').toEqual([]);
  });
});

test.describe('an expired console session', () => {
  test.use({ storageState: STATE_FILES.admin });

  test('a reload after the cookie is gone lands on the console login', async ({ page, context }) => {
    await page.goto('/zh-CN/admin/config', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '配置中心', level: 1 })).toBeVisible();

    await context.clearCookies();
    await page.reload({ waitUntil: 'networkidle' });

    await expect(page).toHaveURL(/\/admin\/login/);
    await expect(page.getByRole('heading', { name: '运维台登录' })).toBeVisible();
    await expect(page.getByText('Runtime ApiError')).toHaveCount(0);
  });

  test('an expired token on a client request returns to login', async ({ page, context }) => {
    await page.goto('/zh-CN/admin/jobs', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '任务运维', level: 1 })).toBeVisible();

    // Cookie gone (browser would stop sending it) plus a 401 on the in-memory
    // bearer (same TTL as the cookie). Clearing cookies also stops the login
    // page from bouncing a still-valid server session back into the console.
    await page.route('**/v1/admin/**', async (route) => {
      if (route.request().url().includes('/v1/admin/auth/login')) {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'AUTH_REQUIRED', message: '请先登录后台。' },
        }),
      });
    });
    await context.clearCookies();

    // `reload` bumps the list token so a request fires even with unchanged filters.
    await page.getByRole('button', { name: '刷新' }).click();
    await expect(page).toHaveURL(/\/admin\/login/);
    await expect(page.getByRole('heading', { name: '运维台登录' })).toBeVisible();
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
    const refreshCalls = watchConsumerRefresh(page);
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });

    for (const service of ['postgres', 'redis', 'minio', 'celery']) {
      await expect(page.getByText(service, { exact: true })).toBeVisible();
    }
    expect(problems(), 'console errors on the health page').toEqual([]);
    expect(refreshCalls(), 'consumer /v1/auth/refresh on the health page').toEqual([]);
  });

  test('the job console lists the seeded jobs', async ({ page }) => {
    await page.goto('/zh-CN/admin', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: '任务运维' }).click();
    await expect(page.getByRole('heading', { name: '任务运维', level: 1 })).toBeVisible();

    // Job ids are what an operator pastes in from an alert, so they belong on
    // screen rather than behind a hover.
    await expect(page.getByText(/^job_/).first()).toBeVisible();
  });

  test('the wedged job detail surfaces its async task and related logs', async ({ page }) => {
    // The seeded async provider task is a best-effort demo fixture: a live
    // `poll_async_provider_tasks` beat tick reaps it (this seed environment has
    // no real media endpoint, so the capability is always "missing from the
    // catalogue") within seconds of `make seed` running, well before this test
    // gets a chance to render it. The section itself is still worth asserting
    // on, so this augments the real detail response with a synthetic
    // `async_task` rather than racing the beat scheduler for one.
    await page.route('**/v1/admin/jobs/job_*', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({
        response,
        body: JSON.stringify({
          ...body,
          async_task: {
            node_id: 'provider_generate',
            capability_name: 'ep_seed_video:image_to_video',
            provider_label: null,
            external_task_id: 'e2e-mock-task-1',
            poll_count: 12,
            next_poll_at: new Date().toISOString(),
            deadline_at: new Date().toISOString(),
            claimed_at: null,
            provider_attempt_id: null,
          },
        }),
      });
    });

    await page.goto('/zh-CN/admin/jobs', { waitUntil: 'networkidle' });

    // Mizuki also owns most of the seed's ordinary succeeded jobs, so this
    // filters to `failed` first — the wedged job lands there once the beat
    // gives up on it (`AsyncProviderTask.deadline_at` already elapsed by
    // seed time) — leaving exactly one Mizuki row to disambiguate on. The
    // user column shows a name, not the raw `usr_...` id. Status is now a
    // multiselect dropdown and the filter bar only applies on "搜索".
    await page.getByRole('button', { name: '状态' }).click();
    await page.getByRole('menuitemcheckbox', { name: '已失败' }).click();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '搜索' }).click();
    const wedgedRow = page.getByRole('row', { name: 'Mizuki' });
    await expect(wedgedRow).toBeVisible();
    await wedgedRow.click();

    await expect(page.getByRole('heading', { name: '异步供应商任务' })).toBeVisible();
    await expect(page.getByText('e2e-mock-task-1')).toBeVisible();

    // The related-logs section reads straight from `/v1/admin/logs?job_id=`,
    // untouched by the mock above, so this is the real seeded runtime-error
    // signal — present whether or not the beat has already reaped the task.
    await expect(page.getByRole('heading', { name: '关联日志' })).toBeVisible();
    await expect(page.getByText('async_task_deadline_exceeded')).toBeVisible();
  });

  test('the credits console surfaces the overdue reservation', async ({ page }) => {
    await page.goto('/zh-CN/admin/credits', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '积分运维', level: 1 })).toBeVisible();

    // The seeded stuck job holds a reservation older than the report's grace
    // period, so this section must not be empty.
    await expect(page.getByRole('heading', { name: '悬挂预扣' })).toBeVisible();
    await expect(page.getByText(/^job_/).first()).toBeVisible();

    const ledger = page.getByRole('heading', { name: '积分账本' }).locator('..');
    const actions = await ledger.getByRole('button').allTextContents();
    expect(actions.indexOf('配置')).toBe(actions.indexOf('刷新') + 1);
    await ledger.getByRole('button', { name: '配置' }).click();
    await expect(page.getByRole('heading', { name: '积分与分成配置' })).toBeVisible();
    await expect(page.getByText('定价矩阵', { exact: true })).toBeVisible();
  });

  test('the config console contains only global flags and shortform specs', async ({ page }) => {
    await page.goto('/zh-CN/admin/config', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '配置中心', level: 1 })).toBeVisible();
    await expect(page.getByText('Feature Flag', { exact: true })).toBeVisible();
    await expect(page.getByText('短视频规格目录', { exact: true })).toBeVisible();
    await expect(page.getByText('定价矩阵', { exact: true })).toHaveCount(0);
  });

  test('the log centre renders its table', async ({ page }) => {
    await page.goto('/zh-CN/admin/audit', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '日志中心', level: 1 })).toBeVisible();
    await expect(page.getByRole('table').first()).toBeVisible();
  });

  test('moderation, reports and appeals share one console via tabs', async ({ page }) => {
    await page.goto('/zh-CN/admin/moderation', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '内容审核', level: 1 })).toBeVisible();
    await expect(page.getByRole('tab', { name: '内容审核', selected: true })).toBeVisible();
    await expect(page.getByText('Night Tide · Neon').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: '内容审核', level: 2 })).toBeVisible();
    await expect(page.getByRole('button', { name: '刷新' })).toBeVisible();
    await expect(page.getByRole('button', { name: '配置' })).toBeVisible();

    await page.getByRole('tab', { name: '举报与申诉' }).click();
    await expect(page.getByRole('table').first()).toBeVisible();

    await page.getByRole('tab', { name: '申诉' }).click();
    await expect(page.getByRole('table').first()).toBeVisible();

    // The old standalone URL keeps working and lands on the reports tab.
    await page.goto('/zh-CN/admin/reports', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL(/\/admin\/moderation\?tab=reports/);
    await expect(page.getByRole('tab', { name: '举报与申诉', selected: true })).toBeVisible();
    await expect(page.getByRole('table').first()).toBeVisible();
  });

  test('the user console finds the suspended seed account', async ({ page }) => {
    await page.goto('/zh-CN/admin/users', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '用户与权限', level: 1 })).toBeVisible();
    await expect(page.getByText(ACCOUNTS.suspended)).toBeVisible();
  });

  test('the agent console reports token spend and degradations', async ({ page }) => {
    await page.goto('/zh-CN/admin/agents', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '智能体', level: 1 })).toBeVisible();
    // Among the seeded runs is a Copy Agent call that fell back to the stub.
    await expect(page.getByText('copy').first()).toBeVisible();
  });

  test('the statistics console aggregates provider, agent, job and credit metrics', async ({
    page,
  }) => {
    await page.goto('/zh-CN/admin/statistics', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '数据统计', level: 1 })).toBeVisible();

    // The module opens on the overview tab; each metric now lives behind its
    // own scenario tab rather than being flattened onto a single page.
    await expect(page.getByRole('tab', { name: '总览', selected: true })).toBeVisible();
    await expect(page.getByRole('tab', { name: '系统与基础设施' })).toHaveCount(0);

    // Providers & agents tab: fake providers are test-only, so production seed
    // data leaves the comparison table empty, but the section always renders.
    await page.getByRole('tab', { name: '供应商与智能体' }).click();
    await expect(page.getByRole('heading', { name: '供应商统计' })).toBeVisible();
    // Agent usage grid: the seeded intent_router run, same source this feature's
    // routing decisions now come from.
    await expect(page.getByText('intent_router').first()).toBeVisible();

    // Jobs tab: renders even though the seeded jobs are older than the 24h
    // window and legitimately count as zero.
    await page.getByRole('tab', { name: '生成与任务' }).click();
    await expect(page.getByRole('heading', { name: '任务吞吐' })).toBeVisible();

    // Credits tab: the reconciliation snapshot always renders.
    await page.getByRole('tab', { name: '积分与账本' }).click();
    await expect(page.getByRole('heading', { name: '积分对账' })).toBeVisible();
  });

  test('the routing console shows the workflow editor without a weights panel', async ({
    page,
  }) => {
    await page.goto('/zh-CN/admin/routing', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '工作流', level: 1 })).toBeVisible();
    // The operation switcher is the workflow editor's own tablist; the old
    // "workflow / providers & weights" console tabs are gone entirely.
    await expect(page.getByRole('tab', { name: '供应商与权重' })).toHaveCount(0);
    await expect(page.getByText('路由权重')).toHaveCount(0);

    const edgePaths = page.locator('.react-flow__edge-path');
    await expect(edgePaths.first()).toBeVisible();
    expect(await edgePaths.count()).toBeGreaterThanOrEqual(14);
    const stroke = await edgePaths.first().evaluate((el) => getComputedStyle(el).stroke);
    expect(stroke).not.toBe('');
    expect(stroke).not.toBe('none');
  });

  test('a sandbox dialog submits a real job and shows live progress', async ({ page }) => {
    // The worker / beat may not be running here, so this does not wait for a
    // real render to finish. GET detail is mocked as `running` so the dialog
    // must show the localised in-flight status rather than a raw enum.
    await page.goto('/zh-CN/admin/routing', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: '沙盒试跑' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '沙盒试跑' })).toBeVisible();
    await expect(dialog.getByLabel('试跑对象')).toHaveValue('draft');
    await expect(dialog.getByText('实时流转')).toBeVisible();
    await dialog.getByLabel('提示词').fill('一只在雨中奔跑的猫');

    const sandboxRun = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && response.url().includes('/sandbox-run'),
    );
    await page.route('**/v1/admin/jobs/job_*', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      const events = Array.isArray(body.events) ? body.events : [];
      await route.fulfill({
        response,
        body: JSON.stringify({
          ...body,
          status: 'running',
          events: events.length
            ? events
            : [
                {
                  sequence: 1,
                  event_type: 'generating',
                  status: 'running',
                  progress: 45,
                  message: '已提交生成任务，正在渲染',
                  node_id: 'provider_generate',
                  created_at: new Date().toISOString(),
                },
              ],
          async_task: {
            node_id: 'provider_generate',
            capability_name: 'ep_e2e:text_to_video',
            provider_label: null,
            external_task_id: 'e2e-sandbox-task',
            poll_count: 0,
            next_poll_at: new Date().toISOString(),
            deadline_at: new Date().toISOString(),
            claimed_at: null,
            provider_attempt_id: null,
          },
        }),
      });
    });

    await dialog.getByRole('button', { name: '开始试跑' }).click();
    const response = await sandboxRun;
    expect(response.status()).toBe(202);
    await expect(dialog.getByText('生成中')).toBeVisible();
    await expect(dialog.getByText('正在渲染，请稍候')).toBeVisible();
    await expect(dialog.getByText('e2e-sandbox-task')).toBeVisible();
    await expect(dialog.getByRole('button', { name: '开始试跑' })).toBeDisabled();
  });

  test('sandbox history lists a previous try-it', async ({ page }) => {
    await page.goto('/zh-CN/admin/routing', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: '沙盒试跑' }).click();

    const sandbox = page.getByRole('dialog');
    await sandbox.getByLabel('提示词').fill('历史回放用的猫');
    const sandboxRun = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && response.url().includes('/sandbox-run'),
    );
    await sandbox.getByRole('button', { name: '开始试跑' }).click();
    expect((await sandboxRun).status()).toBe(202);

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await page.getByRole('button', { name: '试跑历史' }).click();
    const history = page.getByRole('complementary', { name: '试跑历史' });
    await expect(history.getByRole('heading', { name: '试跑历史' })).toBeVisible();
    await expect(history.getByText('历史回放用的猫')).toBeVisible();

    await page.getByRole('button', { name: '关闭试跑历史' }).click();
    await expect(page.getByRole('complementary', { name: '试跑历史' })).toHaveCount(0);

    await page.getByRole('button', { name: '试跑历史' }).click();
    await expect(page.getByRole('complementary', { name: '试跑历史' })).toBeVisible();

    await page.route('**/v1/admin/jobs/job_*', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      await route.fulfill({
        response,
        body: JSON.stringify({
          ...body,
          events: [
            {
              sequence: 1,
              event_type: 'generating',
              status: 'succeeded',
              progress: 100,
              message: '节点已完成',
              node_id: 'provider_generate',
              created_at: new Date().toISOString(),
              payload: { prompt: '历史回放用的猫' },
            },
          ],
        }),
      });
    });

    await page.getByRole('complementary', { name: '试跑历史' }).getByRole('button', { name: /历史回放用的猫/ }).click();
    const detail = page.getByRole('dialog');
    await expect(detail.getByRole('heading', { name: '试跑详情' })).toBeVisible();
    await expect(detail.getByText('实时流转')).toBeVisible();
    await expect(detail.getByText('产出作品')).toBeVisible();

    await detail.getByRole('button', { name: /provider_generate/ }).click();
    await expect(detail.getByText('输入提示词')).toBeVisible();
    await detail.getByRole('button', { name: '收起节点' }).click();
    await expect(detail.getByText('输入提示词')).toHaveCount(0);
  });

  test('a graph that fails validation cannot be published', async ({ page }) => {
    await page.route('**/v1/admin/workflow-templates/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: ['节点 quality_check 的输出端口 retry 没有连线，任务走到该分支会直接失败。'],
          warnings: [],
        }),
      });
    });

    await page.goto('/zh-CN/admin/routing', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: '发布', exact: true }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('图校验未通过')).toBeVisible();
    await expect(dialog.getByText('没有连线，任务走到该分支会直接失败。')).toBeVisible();
    // Blocked so an operator cannot burn an `admin_dangerous` confirmation on
    // a graph already known to fail.
    await expect(dialog.getByRole('button', { name: '发布并生效' })).toBeDisabled();
  });

  test('the models console renders primary/backup lists', async ({ page }) => {
    await page.route('**/v1/admin/llm-providers/*/validate/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          validation_id: 'val_e2e_probe',
          status: 'completed',
          elapsed_ms: 42,
          timeout_ms: 90_000,
          result: {
            endpoint_id: 'ep_e6a55be6a06d',
            kind: 'media',
            target_model: 'minimax-h3',
            probe_type: 'text_to_video',
            reachable: true,
            usable: true,
            latency_ms: 42,
            provider_status_code: 200,
            error_code: null,
            warning_code: null,
            provider_error_code: null,
            provider_error_message: null,
            external_task_id: 'task-live-1',
          },
        }),
      });
    });
    await page.route('**/v1/admin/llm-providers/*/validate', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          validation_id: 'val_e2e_probe',
          status: 'running',
          elapsed_ms: 0,
          timeout_ms: 90_000,
          result: null,
        }),
      });
    });
    await page.goto('/zh-CN/admin/models', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '模型管理', level: 1 })).toBeVisible();

    const refreshed = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' && response.url().includes('/v1/admin/llm-providers'),
    );
    await page.getByRole('button', { name: '刷新' }).click();
    await refreshed;

    // Flat primary/backup list — taxonomy lives in the create/edit dialog.
    await expect(page.getByText('主用节点', { exact: true })).toBeVisible();
    await expect(page.getByText('备用节点', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: '新增模型' }).click();
    await expect(page.getByRole('heading', { name: '新增模型' })).toBeVisible();
    // Switching to a media model swaps the single models field for the
    // per-capability checklist.
    await page.getByLabel('模型类型').selectOption('media');
    await expect(page.getByText('支持的输入类型', { exact: true })).toBeVisible();
    await expect(page.getByLabel('接口协议')).toBeVisible();
    const protocolSelect = page.getByLabel('接口协议');
    await expect(protocolSelect.locator('option[value="openai"]')).toHaveText('OpenAI');
    await expect(protocolSelect.locator('option[value="minimax"]')).toHaveText('MiniMax');
    await expect(protocolSelect.locator('option[value="comfyui"]')).toHaveText('ComfyUI');
    await expect(protocolSelect.locator('option[value="comfyui"]')).toBeDisabled();
    const editorDialog = page.getByRole('dialog');
    await editorDialog.press('Escape');
    await expect(editorDialog).toBeHidden();

    const mediaRow = page
      .getByText('minimax-h3', { exact: true })
      .first()
      .locator('xpath=../../..');
    await mediaRow.getByRole('button', { name: '验证' }).click();
    await expect(page.getByRole('heading', { name: '验证媒体模型' })).toBeVisible();
    await page.getByRole('button', { name: '发送验证请求' }).click();
    await expect(mediaRow.getByText('验证成功')).toBeVisible();
    await expect(mediaRow.getByText('42 ms')).toBeVisible();
    await expect(mediaRow.getByText('任务 task-live-1')).toBeVisible();
  });

  test('the style gallery console lists the seeded catalogue and creates an entry', async ({
    page,
  }) => {
    await page.goto('/zh-CN/admin/style-gallery', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: '画风库', level: 1 })).toBeVisible();

    // Seeded via `back/app/scripts/seed.py`, which is what the studio's style
    // picker dialog and the create page's inspiration wall both read from.
    await expect(page.getByText('日漫').first()).toBeVisible();

    await page.getByRole('button', { name: '新建画风' }).click();
    await expect(page.getByRole('heading', { name: '新建画风' })).toBeVisible();
    const slug = `e2e-style-${Date.now()}`;
    await page.getByLabel('标识（slug）').fill(slug);
    await page.getByLabel('中文名称').fill('E2E 测试画风');
    await page.getByLabel('英文名称').fill('E2E test style');
    await page.getByLabel('日文名称').fill('E2E テスト画風');
    await page.getByRole('button', { name: '保存' }).click();

    await expect(page.getByRole('heading', { name: '新建画风' })).toBeHidden();
    await expect(page.getByText('E2E 测试画风').first()).toBeVisible();
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
    await expect(nav.getByRole('link', { name: '画风库' })).toBeHidden();
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
