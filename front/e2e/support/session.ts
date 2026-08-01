import { expect, type Page } from '@playwright/test';

/**
 * Seed accounts, all sharing one password. Kept in step with
 * `back/app/scripts/seed.py`; a rename there breaks these tests loudly, which is
 * the intent.
 */
export const SEED_PASSWORD = 'Zaolang2026';

export const ACCOUNTS = {
  author: 'linhai@zaolang.dev',
  remixer: 'mizuki@zaolang.dev',
  reviewer: 'reviewer@zaolang.dev',
  operator: 'operator@zaolang.dev',
  admin: 'admin@zaolang.dev',
  suspended: 'driftwood@zaolang.dev',
} as const;

/** Saved sessions, written once by `setup/auth.setup.ts`. */
export const STATE_FILES = {
  admin: 'e2e/.auth/admin.json',
  reviewer: 'e2e/.auth/reviewer.json',
  operator: 'e2e/.auth/operator.json',
  consumer: 'e2e/.auth/consumer.json',
} as const;

/**
 * Signs in through the modal that a protected action opens.
 *
 * Deliberately drives the real form instead of injecting a token: the access
 * token lives in memory only, and the pending-action resumption we want to test
 * is wired to the form's success path.
 */
export async function signInThroughDialog(page: Page, email: string) {
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('邮箱').fill(email);
  await dialog.getByLabel('密码').fill(SEED_PASSWORD);
  await dialog.getByRole('button', { name: '登录', exact: true }).click();
  await expect(dialog).toBeHidden();
}

/** Signs in from the top bar, for tests that just need a session. */
export async function signIn(page: Page, email: string) {
  await page.getByRole('button', { name: '登录', exact: true }).first().click();
  await signInThroughDialog(page, email);
}

/**
 * Requests whose failure is the app working as designed.
 *
 * Session probes are the honest case: the refresh cookie is httpOnly, so the
 * client cannot know whether it has a session without asking, and a 401 for a
 * visitor who does not is the expected answer rather than a defect.
 */
const EXPECTED_FAILURES: { pattern: RegExp; status: number }[] = [
  { pattern: /\/v1\/auth\/refresh$/, status: 401 },
  { pattern: /\/v1\/admin\/auth\/me$/, status: 401 },
];

/**
 * Collects JavaScript errors and unexpected failed responses.
 *
 * Returns a getter rather than asserting, so a test decides when to check.
 * Browser "failed to load resource" console lines are ignored because they
 * carry no URL; the response listener reports the same failures with enough
 * detail to tell a real break from an expected 401.
 */
export function watchForPageErrors(page: Page): () => string[] {
  const problems: string[] = [];

  page.on('console', (message) => {
    const text = message.text();
    if (message.type() !== 'error') return;
    if (text.includes('Failed to load resource')) return;
    problems.push(`console: ${text}`);
  });

  page.on('pageerror', (error) => {
    problems.push(`pageerror: ${error.message}`);
  });

  page.on('response', (response) => {
    const status = response.status();
    if (status < 400) return;
    const url = response.url();
    if (EXPECTED_FAILURES.some((it) => it.status === status && it.pattern.test(url))) return;
    problems.push(`${status}: ${url}`);
  });

  return () => [...problems];
}
