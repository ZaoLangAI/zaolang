import { expect, test, type Locator, type Page } from '@playwright/test';

import { STATE_FILES, watchForPageErrors } from '../support/session';

/** Seed rows point at staging object storage that no longer holds the objects.
 *
 * Two symptoms, one cause: Next's image proxy 404s on the expired URLs, and
 * `preview:from-video` 404s from the storage backend when it tries to read a
 * seeded video that is not there. Both are properties of the demo data, not of
 * the canvas, and they would otherwise mask the failures this spec cares about.
 *
 * Matched narrowly — that exact endpoint, that exact status. A 404 anywhere
 * else, or a different status on this one, still fails the test. */
const isExpiredSeedMedia = (problem: string) =>
  problem.includes('/_next/image?url=') ||
  (problem.includes('404: ') && problem.includes('/preview:from-video'));

/**
 * Selects a canvas node.
 *
 * A raw mouse event, not `locator.click()`: React Flow positions nodes with a
 * transform on its own pane, so `elementFromPoint` resolves to the pane and
 * Playwright's actionability check never settles — while `force` dispatches a
 * click its pointer handlers never turn into a selection. The retry covers
 * `fitView` still moving the node when the box was measured.
 */
async function selectNode(page: Page, node: Locator): Promise<void> {
  await expect(node).toBeVisible();
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const box = await node.boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      if (await node.evaluate((el) => el.classList.contains('selected'))) return;
    }
    await page.waitForTimeout(300);
  }
  throw new Error('the node never became selected');
}

/**
 * The infinite canvas, end to end through the real UI.
 *
 * Desktop-only for the same reason the editor is: `CanvasShell` gates below
 * the `md` breakpoint. Unlike the editor there is no Chrome/Edge requirement
 * (no WebCodecs), which the last test pins down.
 */
test.describe('infinite canvas', () => {
  test.use({ storageState: STATE_FILES.author });

  test('a free canvas can be created, filled and reloaded', async ({ page }) => {
    const problems = watchForPageErrors(page);

    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await expect(page.getByRole('heading', { name: '我的画布' })).toBeVisible();

    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    // The React Flow surface actually mounted, not just the page shell.
    await expect(page.getByTestId('canvas-surface')).toBeVisible();
    await expect(page.getByText('自由画布')).toBeVisible();

    // A free canvas starts empty, so the toolbar is the only way to put
    // anything on it — without this the mode would be unusable.
    await page.getByRole('button', { name: '便签' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(1);

    await page.getByRole('button', { name: '提示词', exact: true }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    // Autosave reports success rather than staying silent.
    await expect(page.getByText('已保存')).toBeVisible({ timeout: 10_000 });

    // The real proof it persisted: a cold reload brings the nodes back.
    await page.reload({ waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    expect(problems().filter((p) => !isExpiredSeedMedia(p))).toEqual([]);

    // Deleting is reachable too, and also survives a reload. A freshly added
    // node lands at the middle of the viewport, which is the one spot no
    // overlay occupies — `.first()` after a `fitView` can sit under the
    // toolbar panel and swallow the click.
    await page.getByRole('button', { name: '图片' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(3);
    const target = page.locator('.react-flow__node').last();

    await selectNode(page, target);

    await page.getByRole('button', { name: '删除所选' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(page.getByText('已保存')).toBeVisible({ timeout: 10_000 });
    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
  });

  test('a drama canvas seeds nodes for the series and its episodes', async ({ page }) => {
    const problems = watchForPageErrors(page);

    // Reach a series the signed-in user owns through the dashboard, so the
    // test never hardcodes a seeded id.
    await page.goto('/zh-CN/create/short', { waitUntil: 'load' });
    const firstSeries = page.locator('a[href*="/create/short/series/"]').first();
    // The roster arrives from a client-side fetch after hydration, so counting
    // straight after `load` races it and always reads zero.
    await firstSeries.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined);
    if (!(await firstSeries.isVisible())) {
      test.skip(true, 'no drama series in the seeded database for this account');
    }
    await firstSeries.click();
    await page.waitForURL(/\/create\/short\/series\//);

    await page.getByRole('button', { name: '画布视图' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);

    await expect(page.getByTestId('canvas-surface')).toBeVisible();
    await expect(page.getByText('短剧画布')).toBeVisible();

    // Seeded automatically from the hydration snapshot: at minimum the
    // series node itself, without the user adding anything.
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    const seeded = await page.locator('.react-flow__node').count();
    expect(seeded).toBeGreaterThan(0);

    // The seeded nodes persist and are not re-invented on each visit. An
    // unchanged count after a reload proves both halves: if seeding re-ran it
    // would mint fresh ids and the count would grow. Deliberately not
    // asserting the "已保存" flash here — on a canvas that was already seeded
    // by an earlier visit there is nothing new to write, so no save fires.
    await page.reload({ waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(seeded);
    expect(problems().filter((p) => !isExpiredSeedMedia(p))).toEqual([]);
  });

  test('a node can be named and given content, and it survives a reload', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    await page.getByRole('button', { name: '便签' }).click();
    const node = page.locator('.react-flow__node').first();
    await expect(node).toBeVisible();

    // Nothing is selected yet, so the panel says so rather than showing an
    // empty form.
    await expect(page.getByText('选中一个节点后在这里编辑。')).toBeVisible();

    await selectNode(page, node);

    // Wait for the save that actually carries the edit. Watching the "已保存"
    // flash instead would pass on the one the node's *creation* already
    // produced, and then race the 600ms typing debounce.
    const saved = page.waitForResponse(
      (response) =>
        response.url().includes('/graph-ops') &&
        response.request().method() === 'POST' &&
        (response.request().postData() ?? '').includes('雨夜'),
      { timeout: 15_000 },
    );
    await page.getByLabel('名称').fill('开场镜头');
    await page.getByLabel('内容').fill('雨夜，霓虹灯下的街角。');
    // The card reflects the name immediately, not only after a round trip.
    await expect(node).toContainText('开场镜头');
    await saved;

    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node').first()).toContainText('开场镜头');
    await selectNode(page, page.locator('.react-flow__node').first());
    await expect(page.getByLabel('内容')).toHaveValue('雨夜，霓虹灯下的街角。');
  });

  test('adding a card right after typing loses neither the name nor the card', async ({ page }) => {
    // The typing commit is debounced. If it fires with the array captured when
    // the keystroke happened, it saves a document that predates the card added
    // a moment later — reverting it.
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    await page.getByRole('button', { name: '便签' }).click();
    await selectNode(page, page.locator('.react-flow__node').first());
    await page.getByLabel('名称').fill('第一张');
    // Immediately, well inside the 600ms window.
    await page.getByRole('button', { name: '图片' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    await page.waitForTimeout(1500);
    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(page.getByText('第一张')).toBeVisible();
  });

  test('a prompt node on a free canvas asks where the result should go', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);

    await page.getByRole('button', { name: '提示词', exact: true }).click();
    await selectNode(page, page.locator('.react-flow__node').first());

    // Empty prompt cannot generate.
    await expect(page.getByRole('button', { name: '用这段提示词生成' })).toBeDisabled();
    await page.getByLabel('提示词').fill('一只在屋顶上的猫');
    await page.getByRole('button', { name: '用这段提示词生成' }).click();

    // A free canvas has no episode of its own, so it asks before handing off —
    // this is what stops its output becoming a disconnected library.
    await expect(page.getByText('这次生成归入哪一集？')).toBeVisible();
    await page.getByRole('button', { name: '去生成' }).click();
    await page.waitForURL(/\/create\/new\?/);
    // The prompt rides along into the studio.
    expect(decodeURIComponent(page.url())).toContain('prompt=一只在屋顶上的猫');
  });

  test('an uploaded picture renders and wires into a prompt as a reference', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    await page.getByRole('button', { name: '图片' }).click();
    await selectNode(page, page.locator('.react-flow__node').first());

    // A 1x1 PNG is enough: what matters is that the asset round-trips and the
    // card renders it from the server-resolved URL, not from the upload's.
    const uploaded = page.waitForResponse(
      (r) => r.url().includes('/v1/uploads/complete') && r.ok(),
      { timeout: 20_000 },
    );
    await page.getByLabel('图片文件').setInputFiles({
      name: 'dot.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
        'base64',
      ),
    });
    await uploaded;

    await expect(page.locator('.react-flow__node img').first()).toBeVisible({ timeout: 15_000 });
    // Not stale. The re-read that fetches the asset's durable URL has to wait
    // for the save carrying the binding; a GET that overtakes it comes back
    // without the asset and the card flips to "已失效".
    await expect(page.getByText('已失效')).toHaveCount(0);

    // A name typed while that re-read is in flight must survive it: the
    // refresh flips `stale`, and adopting the hydrated node wholesale used to
    // take its empty label with it.
    await page.getByLabel('名称').fill('参考：雨夜街角');
    await expect(page.locator('.react-flow__node').first()).toContainText('参考：雨夜街角');
    await page.waitForTimeout(1200);
    await expect(page.locator('.react-flow__node').first()).toContainText('参考：雨夜街角');

    // Wire it into a prompt card: the edge is what makes it a reference.
    await page.getByRole('button', { name: '提示词', exact: true }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    const promptNode = page.locator('.react-flow__node').last();
    await selectNode(page, promptNode);
    await expect(page.getByText('把图片节点连到这张卡片，即可作为参考图一起生成。')).toBeVisible();

    const source = page.locator('.react-flow__node').first().locator('.react-flow__handle-right');
    const target = promptNode.locator('.react-flow__handle-left');
    const from = (await source.boundingBox())!;
    const to = (await target.boundingBox())!;
    const fx = from.x + from.width / 2;
    const fy = from.y + from.height / 2;
    const tx = to.x + to.width / 2;
    const ty = to.y + to.height / 2;
    await page.mouse.move(fx, fy);
    await page.mouse.down();
    // React Flow starts a connection on the first move after pointerdown, so
    // nudge before travelling — jumping straight to the target reads as a
    // click on the handle and drops the gesture.
    await page.mouse.move(fx + 8, fy + 8, { steps: 4 });
    await page.mouse.move(tx, ty, { steps: 16 });
    await page.mouse.move(tx, ty);
    await page.mouse.up();
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    await selectNode(page, promptNode);
    await expect(page.getByText('将带上 1 张参考图')).toBeVisible();

    // Both the picture and the wiring survive a cold reload — the part a
    // stored (expiring) URL, or an edge dropped as dangling, would get wrong.
    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node img').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    // And it rides along into the studio.
    await selectNode(page, page.locator('.react-flow__node').last());
    await page.getByLabel('提示词').fill('把这只猫放到屋顶上');
    await page.getByRole('button', { name: '用这段提示词生成' }).click();
    await expect(page.getByText('这次生成归入哪一集？')).toBeVisible();
    await page.getByRole('button', { name: '去生成' }).click();
    await page.waitForURL(/\/create\/new\?/);
    expect(page.url()).toContain('referenceAssetIds=ast_');
  });

  test('undo and redo walk the board back and forward', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    // Nothing to undo on a fresh board.
    await expect(page.getByRole('button', { name: '撤销' })).toBeDisabled();

    await page.getByRole('button', { name: '便签' }).click();
    await page.getByRole('button', { name: '提示词', exact: true }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    await selectNode(page, page.locator('.react-flow__node').last());
    await page.getByRole('button', { name: '删除所选' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(1);

    await page.getByRole('button', { name: '撤销' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await page.getByRole('button', { name: '重做' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(1);

    // Undo/redo are real edits, not a local-only view — they persist.
    await page.getByRole('button', { name: '撤销' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(page.getByText('已保存')).toBeVisible({ timeout: 10_000 });
    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
  });

  test('keyboard duplicates and deletes, but not while typing', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);

    await page.getByRole('button', { name: '便签' }).click();
    await selectNode(page, page.locator('.react-flow__node').first());

    // The properties panel sits beside the canvas: Backspace inside a field
    // must edit the text, never delete the card under it.
    await page.getByLabel('名称').fill('保留我');
    await page.getByLabel('名称').press('Backspace');
    await expect(page.locator('.react-flow__node')).toHaveCount(1);
    await expect(page.getByLabel('名称')).toHaveValue('保留');

    await selectNode(page, page.locator('.react-flow__node').first());
    await page.keyboard.press('ControlOrMeta+d');
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    await page.keyboard.press('Delete');
    await expect(page.locator('.react-flow__node')).toHaveCount(1);
  });

  test('a canvas can be exported and imported back as a copy', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);

    await page.getByRole('button', { name: '便签' }).click();
    await selectNode(page, page.locator('.react-flow__node').first());
    await page.getByLabel('名称').fill('可导出的便签');
    await page.waitForTimeout(1000);

    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出' }).click();
    const file = await (await download).path();
    expect(file).toBeTruthy();

    // Importing into the same canvas adds a copy rather than colliding on ids.
    await page.getByLabel('导入').setInputFiles(file!);
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(page.getByText('可导出的便签')).toHaveCount(2);
  });

  test('right-clicking a card opens actions for it', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    await page.getByRole('button', { name: '便签' }).click();

    // Select first: the menu offers the selection's actions, which is what a
    // right-click on a card means even when the event resolves to the pane
    // React Flow renders the card on.
    const node = page.locator('.react-flow__node').first();
    await selectNode(page, node);
    const box = (await node.boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: 'right' });

    const menu = page.getByRole('menu', { name: '画布操作' });
    await expect(menu).toBeVisible();
    await menu.getByRole('menuitem', { name: '创建副本' }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(menu).toBeHidden();
  });

  test('camera direction is folded into the generated prompt', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();

    await page.getByRole('button', { name: '提示词', exact: true }).click();
    await selectNode(page, page.locator('.react-flow__node').first());
    await page.getByLabel('提示词').fill('一只在屋顶上的猫');

    // Off by default: a simple prompt should not silently acquire a page of
    // optical language.
    await expect(page.getByLabel('机身')).toHaveCount(0);
    await page.getByLabel('镜头参数').check();
    await page.getByLabel('焦段').selectOption('85');
    await page.getByLabel('光圈').selectOption('1.4');

    // The choices persist like any other card content.
    await page.waitForTimeout(1200);
    await page.goto(canvasUrl, { waitUntil: 'load' });
    await selectNode(page, page.locator('.react-flow__node').first());
    await expect(page.getByLabel('焦段')).toHaveValue('85');
    await expect(page.getByLabel('光圈')).toHaveValue('1.4');

    await page.getByRole('button', { name: '用这段提示词生成' }).click();
    await expect(page.getByText('这次生成归入哪一集？')).toBeVisible();
    await page.getByRole('button', { name: '去生成' }).click();
    await page.waitForURL(/\/create\/new\?/);

    // Read the parameter rather than the raw URL: `URLSearchParams` encodes
    // spaces as `+`, which `decodeURIComponent` does not undo.
    const prompt = new URL(page.url()).searchParams.get('prompt') ?? '';
    // The author's own words stay first, with the lens language appended and
    // the guardrail that keeps a camera out of the picture.
    expect(prompt.startsWith('一只在屋顶上的猫,')).toBe(true);
    expect(prompt).toContain('85mm');
    expect(prompt).toContain('f/1.4');
    expect(prompt).toContain('no camera, lens, tripod, rig or crew may appear');
  });

  test('the director frames a panorama into a shot the canvas can generate from', async ({
    page,
  }) => {
    const scriptUrls: string[] = [];
    page.on('request', (request) => {
      if (request.resourceType() === 'script') scriptUrls.push(request.url());
    });

    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    await expect(page.getByTestId('canvas-surface')).toBeVisible();

    // three.js is several hundred KB. Nobody who never opens the director
    // should be made to download it.
    const chunksBefore = scriptUrls.length;

    await page.getByRole('button', { name: '导演台' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText('先载入一张全景图')).toBeVisible();
    // Cannot capture with nothing loaded.
    await expect(page.getByRole('button', { name: '定格为首帧' })).toBeDisabled();

    // A 2:1 image so the projection is at least geometrically valid.
    await page.getByLabel('载入全景图').setInputFiles({
      name: 'pano.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR42mP8z8BQz0AEYBxVSF8FAG/lA/1xQqmSAAAAAElFTkSuQmCC',
        'base64',
      ),
    });
    await expect(page.getByTestId('panorama-surface')).toBeVisible();
    // The viewer's chunk is fetched on demand, not with the page.
    expect(scriptUrls.length).toBeGreaterThan(chunksBefore);

    await expect(page.getByRole('button', { name: '定格为首帧' })).toBeEnabled({
      timeout: 20_000,
    });
    const uploaded = page.waitForResponse(
      (r) => r.url().includes('/v1/uploads/complete') && r.ok(),
      { timeout: 30_000 },
    );
    await page.getByRole('button', { name: '定格为首帧' }).click();
    await uploaded;
    await expect(page.getByRole('dialog')).toBeHidden();

    // The shot lands as a picture wired into a prompt describing the framing,
    // ready to generate from — the same pair a hand-built one would be.
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);
    await selectNode(page, page.locator('.react-flow__node').last());
    const framing = await page.getByLabel('提示词').inputValue();
    expect(framing).toContain('field of view');
    // The viewpoint guardrail, without which naming a body and a lens reliably
    // returns a photograph of a camera on a tripod.
    expect(framing).toContain('no camera, lens, tripod, rig or crew may appear');
    await expect(page.getByText('将带上 1 张参考图')).toBeVisible();
  });

  test('a change in one window reaches another without a reload', async ({ page }) => {
    // The canvas holds one SSE connection per open canvas, and this is the
    // behaviour it exists for. Deliberately not a reload check: the point is
    // that the second window converges while sitting still.
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();
    await expect(page.getByTestId('canvas-surface')).toBeVisible();

    const second = await page.context().newPage();
    await second.setViewportSize({ width: 1280, height: 900 });
    await second.goto(canvasUrl, { waitUntil: 'load' });
    await expect(second.getByTestId('canvas-surface')).toBeVisible();
    await expect(second.locator('.react-flow__node')).toHaveCount(0);

    try {
      await page.getByRole('button', { name: '便签' }).click();
      await expect(page.locator('.react-flow__node')).toHaveCount(1);
      // No navigation, no refetch on this page — the card arrives on the wire.
      await expect(second.locator('.react-flow__node')).toHaveCount(1, { timeout: 15_000 });

      // A delete has to travel too, and it is the harder half: the row is gone,
      // so it cannot describe itself — the change feed has to carry the tombstone.
      await selectNode(page, page.locator('.react-flow__node').first());
      await page.getByRole('button', { name: '删除所选' }).click();
      await expect(page.locator('.react-flow__node')).toHaveCount(0);
      await expect(second.locator('.react-flow__node')).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await second.close();
    }
  });

  test('a skill picked from the prompt library lands as a live card', async ({ page }) => {
    const problems = watchForPageErrors(page);

    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    const canvasUrl = page.url();
    await expect(page.getByTestId('canvas-surface')).toBeVisible();

    await page.getByRole('button', { name: '提示词库' }).click();
    // The catalogue arrives from a client fetch after hydration.
    const firstSkill = page.getByRole('button', { name: /.+/ }).and(page.locator('li button'));
    await expect(firstSkill.first()).toBeVisible({ timeout: 15_000 });
    await firstSkill.first().click();
    await expect(page.locator('.react-flow__node')).toHaveCount(1);

    // The whole point of `binding_skill_id`: hydration has to resolve a card
    // the canvas itself bound, in a mode that has no episodes to derive it
    // from. Without it this card reads as broken on the very next load.
    await expect(page.getByText('已失效')).toHaveCount(0);
    await expect(page.getByText('已保存')).toBeVisible({ timeout: 10_000 });

    await page.goto(canvasUrl, { waitUntil: 'load' });
    await expect(page.locator('.react-flow__node')).toHaveCount(1);
    await expect(page.getByText('已失效')).toHaveCount(0);
    expect(problems().filter((p) => !isExpiredSeedMedia(p))).toEqual([]);
  });

  test('the canvas is gated by width, not by browser', async ({ page }) => {
    await page.goto('/zh-CN/create/tools/canvas', { waitUntil: 'load' });
    await page.getByRole('button', { name: '新建画布' }).click();
    await page.waitForURL(/\/canvas\/cnv_/);
    await expect(page.getByTestId('canvas-surface')).toBeVisible();

    await page.setViewportSize({ width: 500, height: 900 });
    await expect(page.getByText('请在桌面宽度下使用画布')).toBeVisible();
    await expect(page.getByTestId('canvas-surface')).toHaveCount(0);
  });
});
