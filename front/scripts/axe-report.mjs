/**
 * Prints axe violations with the offending nodes, for fixing them.
 *
 * The Playwright suite asserts pass/fail; this is the diagnostic view, so it
 * names the selector and the measured contrast rather than just the rule id.
 *
 * Usage: node scripts/axe-report.mjs [baseURL] [path ...]
 */
import AxeBuilder from '@axe-core/playwright';
import { chromium } from '@playwright/test';

const [baseURL = 'http://127.0.0.1:3100', ...paths] = process.argv.slice(2);
const targets = paths.length > 0 ? paths : ['/zh-CN/discover'];

const browser = await chromium.launch();

for (const theme of ['dark', 'light']) {
  for (const target of targets) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1024 },
      locale: 'zh-CN',
    });
    await context.addCookies([
      { name: 'zl_theme', value: theme, domain: '127.0.0.1', path: '/' },
    ]);
    const page = await context.newPage();
    await page.goto(`${baseURL}${target}`, { waitUntil: 'networkidle' });

    if (process.env.OPEN_PALETTE === '1') {
      await page.keyboard.press('Meta+k');
      await page.waitForTimeout(300);
    }

    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
      .disableRules(['video-caption'])
      .analyze();

    console.log(`\n=== ${theme} ${target} — ${violations.length} violation(s)`);
    for (const violation of violations) {
      console.log(`\n-- ${violation.id} (${violation.impact}): ${violation.help}`);
      for (const node of violation.nodes.slice(0, 6)) {
        console.log(`   target: ${node.target.join(' ')}`);
        console.log(`   html:   ${node.html.slice(0, 200)}`);
        for (const check of [...node.any, ...node.all]) {
          console.log(`   why:    ${check.message}`);
        }
      }
    }
    await context.close();
  }
}

await browser.close();
