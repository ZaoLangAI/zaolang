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
  await waitForAnimationsToSettle(page);
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
    // If a contrast failure still shows up, this says whether something was
    // mid-flight when axe sampled.
    await testInfo.attach(`animations-${label}.json`, {
      body: JSON.stringify(await runningAnimations(page), null, 2),
      contentType: 'application/json',
    });
  }

  const summary = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? 'n/a'}): ${violation.nodes.length} node(s) — ${violation.help}`,
  );
  expect(summary, `axe violations on ${label}`).toEqual([]);
}

/**
 * Waits for every finite animation, CSS transition and view transition to end.
 *
 * axe computes contrast from the colours on screen at that instant, so a scan
 * that lands inside a fade reads text blended into its background and reports
 * contrast failures that never exist once the page is still. Right after
 * `load` that is not hypothetical: a theme crossfade (`theme-provider.tsx`)
 * can start as soon as the signed-in preference settles, and the studio's
 * option chips were caught at a fraction of their opacity. Infinite
 * animations (spinners) never finish, so they are left out rather than waited
 * on.
 */
async function waitForAnimationsToSettle(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      document
        .getAnimations()
        .every(
          (animation) =>
            animation.playState !== 'running' ||
            animation.effect?.getTiming().iterations === Infinity,
        ),
    undefined,
    { timeout: 5_000 },
  );
}

async function runningAnimations(page: Page) {
  return page.evaluate(() =>
    document
      .getAnimations()
      .filter((animation) => animation.playState === 'running')
      .map((animation) => ({
        type: animation.constructor.name,
        name:
          'animationName' in animation
            ? (animation as CSSAnimation).animationName
            : 'transitionProperty' in animation
              ? (animation as CSSTransition).transitionProperty
              : animation.id,
        target:
          animation.effect instanceof KeyframeEffect
            ? String(
                animation.effect.target?.tagName ?? animation.effect.pseudoElement ?? 'unknown',
              )
            : 'unknown',
      })),
  );
}

/**
 * Asserts nothing overflows horizontally, per the design breakpoints rule.
 *
 * The document check alone is not enough: `body { overflow-x: hidden }` is in
 * the base layer on purpose, and it hides exactly the defect this assertion is
 * looking for. So the page's own containers are measured too — they are plain
 * blocks, so their `scrollWidth` still reports a child that sticks out, while a
 * deliberate sideways rail keeps its overflow inside its own scroll box and is
 * correctly ignored.
 */
export async function expectNoHorizontalOverflow(page: Page, containers = ['main']) {
  const overflow = await page.evaluate((selectors) => {
    const root = document.documentElement;
    const offenders: string[] = [];
    for (const selector of selectors) {
      for (const element of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
        if (element.scrollWidth > element.clientWidth) {
          offenders.push(`${selector}: ${element.scrollWidth} > ${element.clientWidth}`);
        }
      }
    }
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, offenders };
  }, containers);

  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
  expect(overflow.offenders, 'containers wider than their box').toEqual([]);
}
