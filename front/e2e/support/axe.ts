import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, type TestInfo } from '@playwright/test';

/**
 * Runs axe over the current page and fails on any violation.
 *
 * Scoped to WCAG 2.1 A/AA plus the best-practice rules that catch the mistakes
 * this codebase can actually make (landmarks, heading order, region). Violations
 * are attached to the report as JSON so a failure names the node, not just a
 * rule id.
 */
export async function expectNoAxeViolations(page: Page, testInfo: TestInfo, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    // Third-party media controls are not in scope; everything else is ours.
    .disableRules(['video-caption'])
    .analyze();

  if (results.violations.length > 0) {
    await testInfo.attach(`axe-${label}.json`, {
      body: JSON.stringify(results.violations, null, 2),
      contentType: 'application/json',
    });
  }

  const summary = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? 'n/a'}): ${violation.nodes.length} node(s) — ${violation.help}`,
  );
  expect(summary, `axe violations on ${label}`).toEqual([]);
}

/** Asserts nothing overflows horizontally, per the design breakpoints rule. */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth };
  });
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
}
