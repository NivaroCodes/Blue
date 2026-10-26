import { test as base, expect } from '@playwright/test'

// UI and API-contract tests exercise an already authenticated analyst session.
// The login flow has its own tests and never uses this fixture.
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('blue.auth.session.v1', JSON.stringify({
        access_token: 'test-analyst-access-token',
        refresh_token: 'test-analyst-refresh-token',
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: 'test-analyst', email: 'analyst@example.invalid' },
      }))
    })
    await use(page)
  },
})

export { expect }
