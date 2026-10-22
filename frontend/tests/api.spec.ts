import { expect, test } from '@playwright/test'

// Inputs behind the native intro dialog are intentionally inert until it closes.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('kraken.intro.seen.v1', '1'))
})
import type { Page } from '@playwright/test'

const fixture = {
  id: 'api-1',
  platform: 'telegram',
  chat_id: 'api-chat',
  chat_name: 'API Test Group',
  message_id: 'msg-api-1',
  sender_hash: 'hash_01',
  text: 'Контекст из тестового API: вложи 5000 тг.',
  timestamp: new Date().toISOString(),
  status: 'PROCESSED',
  risk_score: 65,
  risk_level: 'HIGH',
  reasons: [{ code: 'MONEY_REQUEST', evidence: 'вложи 5000 тг' }],
  explanation: 'Тест объяснения из API.',
  confidence: 0.8,
  review_status: 'NEW',
  reviewer_note: '',
  model_version: 'test-model',
}
const stats = {
  total_messages: 1,
  pending: 0,
  processing: 0,
  errors: 0,
  by_level: { HIGH: 1, MEDIUM: 0, LOW: 0 },
}
async function apiMode(page: Page, polling = false) {
  await page.addInitScript(
    ({ polling }) =>
      localStorage.setItem(
        'blue.settings.v1',
        JSON.stringify({ mode: 'api', baseUrl: '', polling }),
      ),
    { polling },
  )
}

test('real adapter uses list, stats, detail and review endpoints', async ({ page }) => {
  await apiMode(page)
  let posted: unknown
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/review')) {
      posted = route.request().postDataJSON()
      await route.fulfill({ json: { ...fixture, ...(posted as object) } })
    } else if (path === '/api/stats') await route.fulfill({ json: stats })
    else if (path === '/api/alerts') await route.fulfill({ json: { items: [fixture] } })
    else await route.fulfill({ json: fixture })
  })
  await page.goto('/')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(
    page.locator('.alerts-table').getByText('API Test Group', { exact: true }),
  ).toBeVisible()
  await page.getByRole('link', { name: 'Открыть сообщение api-1' }).click()
  await expect(page.locator('.explanation')).toHaveText('Тест объяснения из API.')
  await page.getByLabel('Статус проверки', { exact: true }).selectOption('REVIEWED')
  await page.getByLabel('Комментарий').fill('Проверено через API')
  await page.getByRole('button', { name: 'Сохранить решение' }).click()
  await expect(page.getByRole('status')).toContainText('на сервере')
  expect(posted).toEqual({ review_status: 'REVIEWED', reviewer_note: 'Проверено через API' })
})

test('API failures show error, retry works, synthetic records never replace the response', async ({
  page,
}) => {
  await apiMode(page)
  let broken = true
  await page.route('**/api/**', (route) =>
    route.fulfill(
      broken
        ? { status: 503, json: { error: 'offline' } }
        : { json: new URL(route.request().url()).pathname === '/api/stats' ? stats : [fixture] },
    ),
  )
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('503')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Демо-сообщение' })).toHaveCount(0)
  broken = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
})

test('malformed processed result is rejected rather than displayed as low risk', async ({
  page,
}) => {
  await apiMode(page)
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/api/stats'
          ? stats
          : [{ ...fixture, risk_score: null, risk_level: null }],
    }),
  )
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('не соответствует контракту')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(0)
})

test('failed review preserves note and never announces success', async ({ page }) => {
  await apiMode(page)
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill(
      path.endsWith('/review')
        ? { status: 500, json: {} }
        : { json: path === '/api/stats' ? stats : path === '/api/alerts' ? [fixture] : fixture },
    )
  })
  await page.goto('/alerts/api-1')
  await page.getByLabel('Комментарий').fill('Не терять комментарий')
  await page.getByRole('button', { name: 'Сохранить решение' }).click()
  await expect(page.getByRole('alert')).toContainText('500')
  await expect(page.getByLabel('Комментарий')).toHaveValue('Не терять комментарий')
  await expect(page.getByRole('status')).toHaveCount(0)
})

test('polling receives new records and pause stops subsequent requests', async ({ page }) => {
  await apiMode(page, true)
  await page.clock.install()
  let requests = 0
  let newMessage = false
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/alerts') requests++
    return route.fulfill({
      json:
        path === '/api/stats'
          ? stats
          : newMessage
            ? [{ ...fixture, id: 'api-2' }, fixture]
            : [fixture],
    })
  })
  await page.goto('/')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  newMessage = true
  await page.clock.fastForward(11_000)
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
  await page.getByRole('button', { name: /Уведомления:/ }).click()
  await expect(page.locator('.notification-popover')).toContainText('Новых сообщений: 1')
  await page.getByRole('button', { name: 'Приостановить live-обновления' }).click()
  await expect(page.getByText('Обновление на паузе', { exact: true })).toBeVisible()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
  const pausedRequests = requests
  await page.clock.fastForward(30_000)
  expect(requests).toBe(pausedRequests)
})

test('settings switch to API, validate URL and remember selected mode', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json: new URL(route.request().url()).pathname === '/api/stats' ? stats : [fixture],
    }),
  )
  await page.goto('/settings')
  await page.getByLabel('Адрес Backend API', { exact: true }).fill('javascript:alert(1)')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('HTTP(S)')
  await page.getByLabel('Адрес Backend API', { exact: true }).fill('')
  await page.getByRole('radio', { name: /Backend API/ }).check()
  await page.getByRole('button', { name: 'Проверить API' }).click()
  await expect(page.getByRole('status')).toContainText('Подключение работает')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await page.goto('/')
  await expect(
    page.locator('.alerts-table').getByText('API Test Group', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.source-pill')).toHaveText('Backend API')
})
