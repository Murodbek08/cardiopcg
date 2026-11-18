import { defineConfig, devices } from '@playwright/test';

// Target: the dev compose stack (deploy/docker-compose.dev.yml) -> http://localhost:8080 (SPA + same-origin /api proxy).
// Prepare it with `bash scripts/setup-e2e.sh`, which also creates the test admin via backend/scripts/create_admin.py.
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  fullyParallel: false,
  workers: 1, // the suite shares one database and builds on created users
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    locale: 'uz-UZ',
    timezoneId: 'Asia/Tashkent',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // phone viewport: only the access / RBAC specs (the clinical UI is tablet/desktop first)
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /01-auth\.spec\.ts/ },
  ],
});
