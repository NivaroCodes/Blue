import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const real = {
  id: 'real-1',
  platform: 'telegram',
  chat_id: 'submitted-chat',
  chat_name: 'Проверка обращений',
  message_id: '42',
  sender_hash: 'anonymous',
  text: 'Вложи 5000 тенге, обещают удвоить взнос.',
  timestamp: new Date().toISOString(),
  status: 'PROCESSED',
  risk_level: 'HIGH',
  risk_score: 80,
  reasons: [],
  explanation: 'Есть признаки риска.',
  confidence: 0.8,
  review_status: 'NEW',
  reviewer_note: '',
  model_version: 'test-model',
}
const seed = {
  ...real,
  id: 'seed-1',
  chat_id: 'blue_demo_synthetic_v1',
  chat_name: 'Blue Demo — Synthetic Chat',
  message_id: 'synthetic-v1-001',
  text: '[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ] Зарплата за вымышленную работу.',
}
const otherSynthetic = [
  { ...real, id: 'flagged', is_synthetic: true },
  { ...real, id: 'seed-by-message', message_id: 'synthetic-v1-002' },
  { ...real, id: 'seed-by-text', text: seed.text },
]
async function api(page: Page, rows: object[], initialMode = 'api') {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(
    (mode) =>
      localStorage.setItem(
        'blue.settings.v1',
        JSON.stringify({
          mode,
          baseUrl: '',
          polling: false,
        }),
      ),
    initialMode,
  )
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({
      json:
        path === '/api/stats'
          ? {
              total_messages: rows.length,
              pending: 0,
              processing: 0,
              errors: 0,
              by_level: { HIGH: rows.length, MEDIUM: 0, LOW: 0 },
            }
          : path === '/api/alerts'
            ? { items: rows }
            : seed,
    })
  })
}
async function open(page: Page, path: string) {
  await page.goto(path)
  await expect(page.locator('.brand-intro')).not.toBeAttached()
}

test('working mode excludes server seeds from inbox, counters, sources and graph', async ({
  page,
}) => {
  await api(page, [real, seed, ...otherSynthetic])
  await open(page, '/')
  await expect(page.locator('.inbox-title')).toContainText('1 сообщений')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.summary-risk.high strong')).toHaveText('1')
  await expect(page.locator('.alerts-table')).not.toContainText('Synthetic Chat')
  await open(page, '/chats')
  await expect(page.locator('.chat-card')).toHaveCount(1)
  await expect(page.locator('main')).not.toContainText('Synthetic Chat')
  await open(page, '/graph')
  await expect(page.getByLabel('Источник графа').locator('option')).toHaveCount(2)
  await expect(page.locator('main')).not.toContainText('Synthetic Chat')
})

test('synthetic-only server data leaves an honest empty working inbox', async ({ page }) => {
  await api(page, [seed])
  await open(page, '/')
  await expect(page.locator('.inbox-title')).toContainText('0 сообщений')
  await expect(page.locator('.summary-risk.high strong')).toHaveText('0')
  await expect(page.locator('.empty-state')).toContainText('Сообщений не найдено')
  await expect(page.getByRole('button', { name: 'Демо-сообщение' })).toHaveCount(0)
})

test('saved switch from demonstration to working data drops all demo records', async ({ page }) => {
  await api(page, [real, seed], 'demo')
  await open(page, '/settings')
  await page.getByRole('radio', { name: /Рабочие данные/ }).check()
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.locator('.source-pill')).toHaveText('Рабочие данные')
  await page.getByRole('link', { name: 'Входящие', exact: true }).click()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.alerts-table')).toContainText(real.chat_name)
  await expect(page.locator('.alerts-table')).not.toContainText(seed.chat_name)
})

test('ordinary real messages mentioning synthetic data are preserved', async ({ page }) => {
  await api(page, [
    { ...real, text: 'Обсуждаем synthetic данные и название Blue Demo — Synthetic Chat.' },
  ])
  await open(page, '/')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
})

test('working export excludes server seeds', async ({ page }) => {
  await api(page, [real, seed])
  await open(page, '/')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Экспорт', exact: true }).click()
  const file = await downloading
  const result = JSON.parse(await readFile((await file.path())!, 'utf8'))
  expect(result.synthetic).toBe(false)
  expect(result.alerts.map((row: { id: string }) => row.id)).toEqual(['real-1'])
})

test('old direct links cannot show a synthetic seed as a working message', async ({ page }) => {
  await api(page, [seed])
  await open(page, '/alerts/seed-1')
  await expect(page.getByRole('alert')).toContainText('Синтетическое сообщение недоступно')
  await expect(page.locator('.original-message')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Сохранить решение' })).toHaveCount(0)
})
