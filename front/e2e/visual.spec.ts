import { expect, test, type Page } from '@playwright/test';

import { expectNoHorizontalOverflow } from './support/axe';
import { STATE_FILES, watchForPageErrors } from './support/session';
import { expectTheme, setTheme } from './support/theme';

/**
 * Dark and light across the three design breakpoints.
 *
 * Screenshots are attached to the report for human review only. What this suite
 * decides on its own is mechanical and still worth failing on: nothing overflows
 * horizontally, and no page logs an error while rendering.
 */

const VIEWPORTS = [
  { label: 'desktop', width: 1440, height: 1024 },
  { label: 'tablet', width: 1024, height: 768 },
  { label: 'mobile', width: 390, height: 844 },
] as const;

const PAGES = [
  { path: '/zh-CN/discover', label: 'discover' },
  { path: '/zh-CN/learn', label: 'learn' },
  { path: '/zh-CN/create', label: 'create' },
  // The vertical studio is the narrowest layout in the product: a phone frame,
  // a form and a fixed submit bar inside a 390px viewport.
  { path: '/zh-CN/create/short', label: 'create-short' },
  { path: '/zh-CN/admin/login', label: 'admin-login' },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const viewport of VIEWPORTS) {
    test.describe(`${theme} · ${viewport.label}`, () => {
      for (const target of PAGES) {
        test(`${target.label} renders without overflow`, async ({ page }, info) => {
          const problems = watchForPageErrors(page);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await setTheme(page, theme);
          await page.goto(target.path, { waitUntil: 'load' });
          await expectTheme(page, theme);

          await expectNoHorizontalOverflow(page);

          await info.attach(`${target.label}-${theme}-${viewport.label}.png`, {
            body: await page.screenshot({ fullPage: true }),
            contentType: 'image/png',
          });

          expect(problems(), `console errors on ${target.label}`).toEqual([]);
        });
      }
    });
  }
}

/**
 * The three pages of the creation chain that need a session and an id.
 *
 * The seed generates ids, so they are read back from the API rather than
 * pinned: a hard-coded id would turn a reseed into a suite-wide failure that
 * says nothing about the layout these tests are actually about.
 */
const API_URL = process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:3001';

async function seededPaths(page: Page) {
  // The refresh cookie rides in the saved storage state; the access token does
  // not exist until it is redeemed, exactly as in the browser.
  const refreshed = await page.request.post(`${API_URL}/v1/auth/refresh`);
  const { access_token: token } = (await refreshed.json()) as { access_token: string };
  const authorization = { authorization: `Bearer ${token}` };

  const works = await page.request.get(`${API_URL}/v1/works`, { params: { limit: 1 } });
  const drafts = await page.request.get(`${API_URL}/v1/drafts`, { headers: authorization });

  const work = ((await works.json()) as { items: Array<{ id: string }> }).items[0];
  const draftItems = (
    (await drafts.json()) as {
      items: Array<{ id: string; latest_job_id?: string; params?: { operation?: string } }>;
    }
  ).items;
  const draft = draftItems[0];
  // Image/video jobs redirect off `/jobs/[jobId]` into the studio; only audio
  // still renders the standalone progress page this label is meant to scan.
  const audioDraft = draftItems.find((item) => item.params?.operation === 'audio_generation');

  return [
    work ? { path: `/zh-CN/work/${work.id}`, label: 'work' } : null,
    audioDraft?.latest_job_id
      ? { path: `/zh-CN/jobs/${audioDraft.latest_job_id}`, label: 'jobs' }
      : null,
    draft ? { path: `/zh-CN/publish/${draft.id}`, label: 'publish' } : null,
  ].filter((entry) => entry !== null);
}

test.describe('signed in', () => {
  test.use({ storageState: STATE_FILES.consumer });

  for (const theme of ['dark', 'light'] as const) {
    for (const viewport of VIEWPORTS) {
      test(`the generation studio's style gallery and more-settings render without overflow · ${theme} · ${viewport.label}`, async ({
        page,
      }, info) => {
        const problems = watchForPageErrors(page);
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await setTheme(page, theme);
        await page.goto('/zh-CN/create/new?mode=text_to_video', { waitUntil: 'load' });
        await expectTheme(page, theme);

        // Below the `lg` breakpoint the params panel — including the style
        // gallery trigger — lives inside a sheet opened from the fixed bottom
        // bar, rather than the aside rendered on wide viewports.
        const styleTrigger = page.getByRole('button', { name: '选择系统画风' });
        if (!(await styleTrigger.isVisible())) {
          await page.getByRole('button', { name: '参数', exact: true }).click();
        }

        await styleTrigger.click();
        // Named explicitly: on narrow viewports the params sheet underneath is
        // itself a `role="dialog"`, so an unscoped lookup is ambiguous.
        const styleDialog = page.getByRole('dialog', { name: '系统画风库' });
        await styleDialog.waitFor();
        await page.waitForTimeout(300);
        await expectNoHorizontalOverflow(page);
        await info.attach(`generation-studio-style-gallery-${theme}-${viewport.label}.png`, {
          body: await page.screenshot({ fullPage: true }),
          contentType: 'image/png',
        });
        await styleDialog.focus();
        await page.keyboard.press('Escape');
        await styleDialog.waitFor({ state: 'hidden' });

        await page.getByRole('button', { name: '更多设置' }).click();
        await expectNoHorizontalOverflow(page);
        await info.attach(`generation-studio-more-settings-${theme}-${viewport.label}.png`, {
          body: await page.screenshot({ fullPage: true }),
          contentType: 'image/png',
        });

        expect(problems(), 'console errors on generation-studio').toEqual([]);
      });

      // Skipped: `make seed` no longer publishes any work or leaves a draft
      // behind (see `back/app/scripts/seed.py`), so `seededPaths()` always
      // comes back empty. Restore once a fixture-creation helper can produce
      // a real work/draft/job for the suite to walk.
      test.skip(`the creation chain renders without overflow · ${theme} · ${viewport.label}`, async ({
        page,
      }, info) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await setTheme(page, theme);
        await page.goto('/zh-CN/collection', { waitUntil: 'load' });

        const targets = await seededPaths(page);
        expect(targets.length, 'seeded work and draft').toBeGreaterThan(0);

        for (const target of targets) {
          // Not `networkidle`: the job page holds a live progress stream open, so
          // the network never goes idle and the wait would always time out.
          await page.goto(target.path, { waitUntil: 'domcontentloaded' });
          await page.waitForLoadState('load');
          await expectTheme(page, theme);
          await expectNoHorizontalOverflow(page);

          await info.attach(`${target.label}-${theme}-${viewport.label}.png`, {
            body: await page.screenshot({ fullPage: true }),
            contentType: 'image/png',
          });
        }
      });
    }
  }
});

test.describe('reduced motion', () => {
  test('animations are suppressed when the user asks for it', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/zh-CN/discover', { waitUntil: 'load' });

    // Every animated element must resolve to an effectively instant duration;
    // a leftover long transition is what makes reduced-motion users seasick.
    const longAnimations = await page.evaluate(() => {
      const offenders: string[] = [];
      for (const element of Array.from(document.querySelectorAll('*'))) {
        const style = getComputedStyle(element);
        const durations = [style.transitionDuration, style.animationDuration]
          .join(',')
          .split(',')
          .map((value) => Number.parseFloat(value) || 0);
        if (durations.some((duration) => duration > 0.05)) {
          offenders.push(element.tagName.toLowerCase());
        }
      }
      return offenders.slice(0, 10);
    });

    expect(longAnimations).toEqual([]);
  });
});
