import { expect, test } from '@playwright/test'

test('analyst sees login and opens dashboard after a valid Auth response', async ({ page }) => {
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'test-analyst-access-token',
        refresh_token: 'test-analyst-refresh-token',
        expires_in: 3600,
        user: { id: 'test-analyst', email: 'analyst@example.invalid' },
      }),
    })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Вход аналитика' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Войти' })).toBeEnabled()
  await page.getByLabel('Email').fill('analyst@example.invalid')
  await page.getByLabel('Пароль').fill('test-password')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'Вход аналитика' })).not.toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Главная навигация' })).toBeVisible()
})
