import { defineConfig, devices } from '@playwright/test';

/**
 * Three suites, deliberately separate.
 *
 * `e2e` walks the product flows, `a11y` runs axe over the same pages, and
 * `visual-qa` takes the dark/light × three-viewport screenshots the design
 * acceptance needs. None of them run in CI: they need Postgres, Redis, MinIO and
 * a seeded database, so they are local gates driven from the Makefile.
 */
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 3100);
// `localhost`, not `127.0.0.1`: the console session cookie is SameSite=Strict,
// and a browser treats those two as different sites, which would silently drop
// the cookie the API sets and make every authenticated flow fail.
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  // Serial by default: the suites share one seeded database, and parallel
  // workers publishing works would make each other's assertions flaky.
  workers: 1,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  outputDir: 'test-results',

  use: {
    baseURL,
    locale: 'zh-CN',
    timezoneId: 'UTC',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      // Logs in once per role and saves the cookies, so the flow suite does not
      // spend the login rate-limit budget on setup.
      name: 'setup',
      testMatch: /setup\/.*\.setup\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1024 } },
    },
    {
      name: 'e2e',
      testMatch: /flows\/.*\.spec\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1024 } },
    },
    {
      name: 'a11y',
      testMatch: /a11y\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1024 } },
    },
    {
      name: 'visual-qa',
      testMatch: /visual\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: `npm run build && npm run start -- --port ${PORT}`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
});
