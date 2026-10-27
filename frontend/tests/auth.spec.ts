import { expect, test } from '@playwright/test'

test('analyst sees login and opens dashboard after a valid Auth response', async ({ page }) => {
  let signInRequests = 0
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    signInRequests++
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
  await expect(page.getByLabel('Email')).toHaveValue('info@gmail.com')
  await expect(page.getByLabel('Пароль')).toHaveValue('info67')
  await expect(page.getByLabel('Пароль')).toHaveAttribute('type', 'password')
  expect(signInRequests).toBe(0)
  await expect(page.getByRole('button', { name: 'Войти' })).toBeEnabled()
  await page.getByLabel('Email').fill('analyst@example.invalid')
  await page.getByLabel('Пароль').fill('test-password')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'Вход аналитика' })).not.toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Главная навигация' })).toBeVisible()
  expect(signInRequests).toBe(1)
})

test('wrong password and connection errors remain visible without signing in', async ({ page }) => {
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    await route.fulfill({ status: 400, json: { error: 'invalid_grant' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('alert')).toContainText('Проверьте email и пароль')
  await expect(page.getByRole('heading', { name: 'Вход аналитика' })).toBeVisible()

  await page.unroute('https://blue-test.supabase.co/auth/v1/token?grant_type=password')
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    await route.fulfill({ status: 503, json: { error: 'unavailable' } })
  })
  await page.getByLabel('Email').fill('different@example.invalid')
  await page.getByLabel('Пароль').fill('different-password')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('alert')).toContainText('Сервис входа временно недоступен')
  await expect(page.getByRole('heading', { name: 'Вход аналитика' })).toBeVisible()

  await page.unroute('https://blue-test.supabase.co/auth/v1/token?grant_type=password')
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    await route.abort('failed')
  })
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось подключиться к сервису входа')
})

test('public demo login displays only synthetic data with server actions disabled', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('blue.settings.v1', JSON.stringify({
    mode: 'api', baseUrl: '', polling: false,
  })))
  const base = {
    platform: 'telegram', chat_id: 'blue_demo_synthetic_v1', chat_name: 'Blue Demo',
    message_id: 'synthetic-v1-001', sender_hash: 'synthetic-person-01',
    timestamp: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(), status: 'PROCESSED', risk_score: 65,
    risk_level: 'HIGH', reasons: [], explanation: 'Synthetic analysis',
    confidence: 0.8, review_status: 'NEW', reviewer_note: '', model_version: 'test-double',
  }
  const synthetic = { ...base, id: 'alert_synthetic', text: '[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ] Вымышленный пример' }
  const live = { ...base, id: 'alert_live', chat_id: 'real-chat', message_id: 'live-1', text: 'Private working message' }
  await page.route('https://blue-test.supabase.co/auth/v1/token?grant_type=password', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ email: 'info@gmail.com', password: 'info67' })
    await route.fulfill({ json: {
      access_token: 'public-demo-test-token', refresh_token: 'public-demo-refresh-token',
      expires_in: 3600, user: { id: '2966cfdd-a65f-45de-83fe-18cd0674bc63', email: 'info@gmail.com' },
    } })
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/stats') return route.fulfill({ json: {
      total_messages: 1, last_24h: 1, pending: 0, processing: 0, errors: 0,
      off_topic: 0, by_level: { HIGH: 1, MEDIUM: 0, LOW: 0 },
    } })
    if (path === '/api/alerts') return route.fulfill({ json: [synthetic, live] })
    if (path === '/api/alerts/alert_synthetic') return route.fulfill({ json: synthetic })
    if (path === '/api/alerts/alert_live') return route.fulfill({ json: live })
    return route.fulfill({ status: 404, json: { detail: 'Not found' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.locator('.alerts-table')).toContainText('Вымышленный пример')
  await expect(page.locator('.alerts-table')).not.toContainText('Private working message')
  await expect(page.getByRole('button', { name: 'Не по теме' })).toHaveCount(0)
  await page.goto('/alerts/alert_synthetic')
  await expect(page.getByRole('button', { name: 'Сохранить решение' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Не по теме — скрыть из очереди' })).toHaveCount(0)
  await page.goto('/alerts/alert_live')
  await expect(page.getByText('Сообщение недоступно для этого аккаунта.')).toBeVisible()
})
