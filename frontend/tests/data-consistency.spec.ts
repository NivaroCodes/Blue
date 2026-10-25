import { expect, test } from './fixtures'
import type { Page, Route } from '@playwright/test'
import { sourceSummaries } from '../src/lib/analytics'
import { AlertSchema } from '../src/lib/model'

const now = Date.parse('2026-10-23T12:00:00Z')
const fixture = AlertSchema.parse({
  id: 'check-1', platform: 'telegram', chat_id: '123', chat_name: 'Telegram source',
  message_id: 'm1', sender_hash: 'sender', text: 'Message for review',
  timestamp: new Date(now - 60_000).toISOString(), status: 'PROCESSED',
  risk_score: 70, risk_level: 'HIGH', review_status: 'NEW', reviewer_note: '',
})
const whatsapp = { ...fixture, id: 'check-2', platform: 'whatsapp' as const, chat_name: 'WhatsApp source' }
const stats = { total_messages: 2, pending: 0, processing: 0, errors: 0, by_level: { HIGH: 2, MEDIUM: 0, LOW: 0 } }

async function setup(page: Page, polling = false) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.clock.install({ time: now })
  await page.addInitScript(({ polling }) => localStorage.setItem('blue.settings.v1',
    JSON.stringify({ mode: 'api', baseUrl: '', polling })), { polling })
}

test('same chat ID on different platforms represents two independent sources', () => {
  const groups = sourceSummaries([fixture, whatsapp])
  expect(groups).toHaveLength(2)
  expect(groups.every(group => group.messages.every(message => message.platform === group.platform))).toBe(true)
})

test('source links and graph keep overlapping platform IDs separate', async ({ page }) => {
  await setup(page)
  await page.route('**/api/**', route => route.fulfill({ json:
    new URL(route.request().url()).pathname === '/api/stats' ? stats : [fixture, whatsapp] }))
  await page.goto('/chats')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.chat-card')).toHaveCount(2)
  await page.locator('.chat-card').filter({ hasText: 'WhatsApp source' }).getByRole('link').click()
  await expect(page).toHaveURL(/platform=whatsapp/)
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.alerts-table')).toContainText('WhatsApp source')
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.source-analytics-list > a')).toHaveCount(2)
  await page.locator('.source-analytics-list > a').filter({ hasText: 'Telegram source' }).click()
  await expect(page).toHaveURL(/platform=telegram/)
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await page.goto('/graph')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.getByLabel('Источник графа').selectOption({ label: 'WhatsApp source' })
  await expect(page.locator('.graph-message-list a')).toHaveCount(1)
  await expect(page.locator('.graph-message-list')).toContainText('WhatsApp source')
})

test('analytics and inbox share the paused snapshot time and exclude future records', async ({ page }) => {
  await setup(page)
  const boundary = { ...fixture, id: 'boundary', timestamp: new Date(now - 24 * 3600_000 + 30_000).toISOString() }
  const future = { ...fixture, id: 'future', timestamp: new Date(now + 60_000).toISOString() }
  await page.route('**/api/**', route => route.fulfill({ json:
    new URL(route.request().url()).pathname === '/api/stats' ? stats : [boundary, future] }))
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.analytics-overview > div').first().locator('strong')).toHaveText('1')
  await page.clock.fastForward(120_000)
  await page.locator('.analytics-overview > a.high').click()
  await expect(page.getByRole('link', { name: 'Открыть сообщение boundary', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Открыть сообщение future', exact: true })).toHaveCount(0)
})

test('changing platform clears the previous source instead of retaining a hidden chat filter', async ({ page }) => {
  await setup(page)
  const other = { ...whatsapp, chat_id: '456' }
  await page.route('**/api/**', route => route.fulfill({ json:
    new URL(route.request().url()).pathname === '/api/stats' ? stats : [fixture, other] }))
  await page.goto('/?chat=123&platform=telegram')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await page.locator('.filter-disclosure summary').click()
  await page.getByLabel('Платформа', { exact: true }).selectOption('whatsapp')
  await expect(page.getByLabel('Чат', { exact: true })).toHaveValue('')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.alerts-table')).toContainText('WhatsApp source')
  expect(new URL(page.url()).searchParams.has('chat')).toBe(false)
})

test('an older polling response cannot undo a successful review or erase a new draft', async ({ page }) => {
  await setup(page, true)
  let hold = false
  let held: Route | undefined
  let saved = fixture
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/review')) {
      saved = { ...fixture, ...route.request().postDataJSON() }
      return route.fulfill({ json: saved })
    }
    if (path === '/api/stats') return route.fulfill({ json: stats })
    if (path === '/api/alerts' && hold) { held = route; return }
    return route.fulfill({ json: path === '/api/alerts' ? [saved] : fixture })
  })
  await page.goto('/alerts/check-1')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByLabel('Комментарий')).toBeEnabled()
  hold = true
  await page.clock.fastForward(11_000)
  await expect.poll(() => Boolean(held)).toBe(true)
  await page.getByLabel('Статус проверки', { exact: true }).selectOption('REVIEWED')
  await page.getByLabel('Комментарий').fill('Saved note')
  await page.getByRole('button', { name: 'Сохранить решение' }).click()
  await expect(page.getByRole('status')).toContainText('Решение сохранено')
  await page.getByLabel('Комментарий').fill('Next draft')
  await held!.fulfill({ json: [fixture] })
  await page.clock.runFor(50)
  await expect(page.getByLabel('Статус проверки', { exact: true })).toHaveValue('REVIEWED')
  await expect(page.getByLabel('Комментарий')).toHaveValue('Next draft')
  hold = false
  // A later snapshot must still accept changes from another analyst.
  saved = { ...saved, review_status: 'FALSE_POSITIVE', reviewer_note: 'External decision' }
  await page.clock.fastForward(11_000)
  await expect(page.getByLabel('Статус проверки', { exact: true })).toHaveValue('FALSE_POSITIVE')
  await expect(page.getByLabel('Комментарий')).toHaveValue('External decision')
})

test('message detail reports polling failure while preserving the loaded message', async ({ page }) => {
  await setup(page, true)
  let broken = false
  await page.route('**/api/**', route => route.fulfill(broken ? { status: 503, json: {} } : { json:
    new URL(route.request().url()).pathname === '/api/stats' ? stats :
      new URL(route.request().url()).pathname === '/api/alerts' ? [fixture] : fixture }))
  await page.goto('/alerts/check-1')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.original-message')).toContainText(fixture.text)
  broken = true
  await page.clock.fastForward(11_000)
  await expect(page.getByRole('alert')).toContainText('API вернул 503')
  await expect(page.locator('.original-message')).toContainText(fixture.text)
  broken = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
