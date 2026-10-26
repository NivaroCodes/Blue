import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: true,
  workers: 2,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    channel: process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? undefined : 'chrome',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    env: {
      VITE_SUPABASE_URL: 'https://blue-test.supabase.co',
      VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test-only',
    },
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
