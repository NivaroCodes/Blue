import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

test('risk, text, chat and platform filters work together; pagination and empty state', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(6)
  await page.getByRole('button', { name: 'Следующая страница' }).click()
  await expect(page.getByRole('button', { name: 'Страница 2', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await page.locator('.filter-disclosure summary').click()
  await page.getByLabel('Уровень риска', { exact: true }).selectOption('HIGH')
  await expect(page.locator('.alerts-table .risk-badge:not(.high)')).toHaveCount(0)
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(6)
  await page.getByLabel('Платформа', { exact: true }).selectOption('whatsapp')
  await expect(page.locator('.alerts-table .platform-telegram')).toHaveCount(0)
  await page.getByLabel('Чат', { exact: true }).selectOption('whatsapp:wa_income')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(4)
  await page.getByLabel('Поиск сообщений').fill('zz-no-match-zz')
  await expect(page.getByRole('heading', { name: 'Сообщений не найдено' })).toBeVisible()
  await page.getByRole('button', { name: 'Сбросить фильтры', exact: true }).click()
  await page.getByLabel('Поиск сообщений').fill('Бесплатная лекция')
  // The text occurs in a processed low-risk example and a processing example.
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.alerts-table .risk-badge.low')).toBeVisible()
})

test('evidence is highlighted and analyst review persists through reload', async ({ page }) => {
  await page.goto('/alerts/demo-1')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('mark')).toHaveCount(4)
  await expect(page.locator('.original-message')).toContainText('Вложи 5 000 ₸')
  await page.getByLabel('Статус проверки', { exact: true }).selectOption('FALSE_POSITIVE')
  await page.getByLabel('Комментарий').fill('Контекст проверен: учебный синтетический пример.')
  await page.getByRole('button', { name: 'Сохранить решение' }).click()
  await expect(page.getByRole('status')).toContainText('Решение сохранено')
  await page.reload()
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByLabel('Статус проверки', { exact: true })).toHaveValue('FALSE_POSITIVE')
  await expect(page.getByLabel('Комментарий')).toHaveValue(
    'Контекст проверен: учебный синтетический пример.',
  )
  await page.getByRole('link', { name: 'Назад к мониторингу' }).click()
  await page.locator('.filter-disclosure summary').click()
  await page.getByLabel('Статус проверки', { exact: true }).selectOption('FALSE_POSITIVE')
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(2)
})

test('chat navigation, direct links and pending state', async ({ page }) => {
  await page.goto('/chats')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.chat-card')).toHaveCount(5)
  await page.getByLabel('Поиск чатов').fill('Табыс')
  await expect(page.locator('.chat-card')).toHaveCount(1)
  await page.getByRole('link', { name: 'Открыть сообщения' }).click()
  await page.locator('.filter-disclosure summary').click()
  await expect(page.getByLabel('Чат', { exact: true })).toHaveValue('whatsapp:wa_income')
  await page.goto('/alerts/demo-pipeline-0')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('button', { name: 'Сохранить решение' })).toBeDisabled()
  await expect(page.locator('.score-number')).toContainText('—')
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('heading', { name: 'Аналитика' })).toBeVisible()
  await expect(page.locator('.metrics-note')).toContainText('не заменяют такую проверку')
})

test('demo live signal appears and filtered JSON export carries synthetic label', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.alerts-table tbody tr')).toHaveCount(6)
  await page.getByRole('button', { name: 'Демо-сообщение' }).click()
  await expect(
    page.getByRole('link', { name: 'Открыть сообщение demo-live-0', exact: true }),
  ).toBeVisible()
  await page.locator('.filter-disclosure summary').click()
  await page.getByLabel('Уровень риска', { exact: true }).selectOption('HIGH')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Экспорт', exact: true }).click()
  const file = await download
  const exported = JSON.parse(await readFile((await file.path())!, 'utf8'))
  expect(exported.synthetic).toBe(true)
  expect(exported.alerts.length).toBe(13)
  expect(exported.alerts.every((a: { risk_level: string }) => a.risk_level === 'HIGH')).toBe(true)
})

test('help dialog is keyboard dismissible and unknown routes are recoverable', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.getByRole('button', { name: 'О проекте' }).click()
  await expect(page.locator('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('dialog')).not.toBeVisible()
  await page.goto('/unknown-page')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.getByRole('link', { name: 'К мониторингу', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
})

for (const width of [375, 768, 1024, 1440]) {
  test(`layouts remain within viewport at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const path of ['/', '/chats', '/graph', '/analytics', '/settings', '/alerts/demo-1']) {
      await page.goto(path)
      await expect(page.locator('.brand-intro')).not.toBeAttached()
      await expect(page.locator('main h1')).toBeVisible()
      const dimensions = await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
      }))
      expect(dimensions.scroll, path).toBeLessThanOrEqual(dimensions.width + 1)
    }
    if (width === 375) {
      await page.getByRole('link', { name: 'Чаты и источники' }).click()
      await expect(page).toHaveURL(/\/chats$/)
    }
  })
}
