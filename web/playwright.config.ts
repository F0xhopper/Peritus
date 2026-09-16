import { defineConfig, devices } from '@playwright/test'

/**
 * Six device projects, plus a reduced-motion pass.
 *
 * Every project runs the whole suite, because the responsive tiers are not a
 * cosmetic layer over one layout — the ledger is a table at `lg`, a scrolling
 * table at `md` and a card list below it, and the context panel is inline, an
 * overlay, or a bottom sheet depending on width. A suite that only ran at 1440
 * would not have tested those at all.
 *
 * `webServer` starts both the mock API and `next start`, so `npx playwright
 * test` is the whole command with nothing to set up first.
 */
const PORT = Number(process.env.PORT || 3100)
const MOCK_API_PORT = Number(process.env.MOCK_API_PORT || 8787)
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/mock-api/**'],
  // The suite touches shared mock state (experts get built and deleted), so
  // workers are serialised within a project rather than racing each other.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Dark is the design; the light theme is covered by its own test.
    colorScheme: 'dark',
  },

  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'laptop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    { name: 'ipad-portrait', use: { ...devices['iPad (gen 7)'] } },
    { name: 'ipad-landscape', use: { ...devices['iPad (gen 7) landscape'] } },
    { name: 'iphone', use: { ...devices['iPhone 15'] } },
    { name: 'pixel', use: { ...devices['Pixel 7'] } },
    {
      // The same suite with animation off. Under `prefers-reduced-motion` the
      // two longer duration tokens are zero, sheets do not slide and the
      // pulses are static — none of which may break an interaction.
      name: 'reduced-motion',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        reducedMotion: 'reduce',
      },
    },
  ],

  webServer: [
    {
      command: `MOCK_API_PORT=${MOCK_API_PORT} node e2e/mock-api/server.mjs`,
      url: `http://127.0.0.1:${MOCK_API_PORT}/auth/status`,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // `next start`, not `next dev`: the suite has to run against the build
      // that would be deployed, and Strict Mode's double effects in dev would
      // mask exactly the stream-abort bugs this suite exists to catch.
      command: `npx next start --port ${PORT}`,
      url: BASE_URL,
      // **Never reused, even locally.** `next start` holds the build manifest it
      // booted with, so a server left running from before a rebuild serves 500s
      // for every renamed chunk — the page then loads with no CSS and no
      // JavaScript, and every assertion fails for a reason that has nothing to
      // do with the code. Twenty seconds of startup is worth not debugging that
      // twice.
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        PERITUS_API_URL: `http://127.0.0.1:${MOCK_API_PORT}`,
        NEXT_PUBLIC_APP_URL: BASE_URL,
        // The suite drives a production build over plain http, and WebKit
        // refuses a `Secure` cookie over http even on loopback — so the whole
        // sign-in path would be untestable on the two projects that catch iOS
        // bugs. Deliberately opt-in; see `isProduction` in lib/auth/cookies.ts.
        PERITUS_ALLOW_INSECURE_COOKIES: 'true',
      },
    },
  ],
})
