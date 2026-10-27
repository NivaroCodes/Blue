import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'

function alert(id: string, text: string, status: 'PROCESSED' | 'OFF_TOPIC' = 'PROCESSED', score = 0) {
  return {
    id,
    platform: id === 'hidden-whatsapp' ? 'whatsapp' : 'telegram',
    chat_id: id === 'hidden-whatsapp' ? 'wa-chat' : 'tg-chat',
    chat_name: id === 'hidden-whatsapp' ? 'Архивный источник' : 'Проверочная группа',
    message_id: id,
    sender_hash: 'synthetic-sender',
    text,
    timestamp: new Date().toISOString(),
    status,
    risk_score: score,
    risk_level: score >= 60 ? 'HIGH' : 'LOW',
    reasons: [],
    explanation: 'Синтетическое объяснение сохранено.',
    confidence: 0.8,
    review_status: id === 'limits-exclamation' ? 'REVIEWED' : 'NEW',
    reviewer_note: id === 'limits-exclamation' ? 'Синтетическая история проверки' : '',
    model_version: 'test-double',
  }
}

async function setup(page: Page) {
  const rows = [
    alert('limits-exclamation', 'ЛИМИТЫ ЖЕ', 'OFF_TOPIC'),
    alert('short-ok', 'ок', 'OFF_TOPIC'),
    alert('again', 'заново', 'OFF_TOPIC'),
    alert('rude-only', 'БЛЯЯЯЯТЬЯ', 'OFF_TOPIC'),
    alert('hidden-whatsapp', 'Нерелевантная заметка', 'OFF_TOPIC'),
    alert('hidden-extra-1', 'Вымышленная заметка 1', 'OFF_TOPIC'),
    alert('hidden-extra-2', 'Вымышленная заметка 2', 'OFF_TOPIC'),
    alert('hidden-extra-3', 'Вымышленная заметка 3', 'OFF_TOPIC'),
    alert('financial-limits', 'Лимиты переводов для вложений требуют проверки'),
    alert('financial-profanity', 'Бля, вложи 5000 тг и приведи друзей', 'PROCESSED', 85),
    alert('low-relevant', 'Напоминание о финансовой грамотности'),
  ]
  await page.addInitScript(() => localStorage.setItem('blue.settings.v1', JSON.stringify({
    mode: 'api', baseUrl: '', polling: false,
  })))
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/stats') return route.fulfill({ json: {
      total_messages: rows.length, pending: 0, processing: 0, errors: 0,
      off_topic: rows.filter((item) => item.status === 'OFF_TOPIC').length,
      by_level: { HIGH: 1, MEDIUM: 0, LOW: 2 },
    } })
    if (url.pathname === '/api/alerts') return route.fulfill({ json: rows })
    const id = decodeURIComponent(url.pathname.split('/')[3])
    const index = rows.findIndex((item) => item.id === id)
    if (index < 0) return route.fulfill({ status: 404, json: { detail: 'Not found' } })
    if (url.pathname.endsWith('/visibility') && route.request().method() === 'POST') {
      const requested = route.request().postDataJSON() as { off_topic: boolean }
      rows[index] = { ...rows[index], status: requested.off_topic ? 'OFF_TOPIC' : 'PROCESSED' }
    }
    return route.fulfill({ json: rows[index] })
  })
  return rows
}

test('main queue stays focused while hidden records remain searchable and paginated', async ({ page }) => {
  await setup(page)
  await page.goto('/?period=all')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(3)
  await expect(page.locator('.inbox-tabs')).toContainText('Нерелевантные 8')
  await expect(page.locator('.alerts-table')).toContainText('Лимиты переводов')
  await expect(page.locator('.alerts-table')).toContainText('Бля, вложи 5000')
  await expect(page.locator('.alerts-table')).not.toContainText('ЛИМИТЫ ЖЕ')
  await expect(page.getByRole('button', { name: /Высокий 1/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Низкий 2/ })).toBeVisible()

  await page.getByRole('button', { name: /Нерелевантные 8/ }).click()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(6)
  await page.getByRole('button', { name: 'Следующая страница' }).click()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
  await page.getByLabel('Поиск сообщений').fill('ЛИМИТЫ ЖЕ')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.alerts-table')).not.toContainText('Лимиты переводов')
  await page.getByLabel('Поиск сообщений').fill('Архивный источник')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await page.locator('.filter-disclosure summary').click()
  await page.getByLabel('Платформа', { exact: true }).selectOption('whatsapp')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await page.getByLabel('Статус проверки', { exact: true }).selectOption('REVIEWED')
  await expect(page.getByRole('heading', { name: 'Сообщений не найдено' })).toBeVisible()
})

test('one record can be hidden and restored without changing analysis or review', async ({ page }) => {
  const rows = await setup(page)
  page.on('dialog', (dialog) => void dialog.accept())
  await page.goto('/?period=all')
  const row = page.locator('.alerts-table tbody tr', { hasText: 'Лимиты переводов' })
  await expect(page.locator('.risk-summary .summary-risk.low strong')).toHaveText('2')
  await row.getByRole('button', { name: 'Не по теме' }).click()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.risk-summary .summary-risk.low strong')).toHaveText('1')
  await expect(page.locator('.inbox-tabs')).toContainText('Нерелевантные 9')
  await page.getByRole('button', { name: /Нерелевантные 9/ }).click()
  await page.getByLabel('Поиск сообщений').fill('Лимиты переводов')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(1)
  await page.getByRole('button', { name: 'Восстановить' }).click()
  await expect(page.getByRole('heading', { name: 'Сообщений не найдено' })).toBeVisible()
  await expect(page.locator('.risk-summary .summary-risk.low strong')).toHaveText('2')
  await expect(page.locator('.inbox-tabs')).toContainText('Нерелевантные 8')
  expect(rows.find((item) => item.id === 'financial-limits')).toMatchObject({
    status: 'PROCESSED', risk_score: 0, explanation: 'Синтетическое объяснение сохранено.',
  })
  await page.goto('/alerts/limits-exclamation')
  await expect(page.locator('.original-message')).toContainText('ЛИМИТЫ ЖЕ')
  await expect(page.locator('.score-number')).toContainText('0')
  await expect(page.getByLabel('Статус проверки', { exact: true })).toHaveValue('REVIEWED')
  await expect(page.getByLabel('Комментарий')).toHaveValue('Синтетическая история проверки')
  await page.getByRole('button', { name: 'Восстановить в основной очереди' }).click()
  await expect(page.getByRole('button', { name: 'Не по теме — скрыть из очереди' })).toBeVisible()
  await expect(page.getByLabel('Статус проверки', { exact: true })).toHaveValue('REVIEWED')
})
