import { expect, test } from './fixtures'

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
})

test('analyst settings contain no server address, port or backend terminology', async ({
  page,
}) => {
  await page.goto('/settings')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('textbox', { name: /Backend|адрес/i })).toHaveCount(0)
  await expect(page.locator('main')).not.toContainText(/127\.0|8000|Vite|Backend API|\/api/)
})

test('inbox shows Telegram and WhatsApp brand assets and risk summaries from the dataset', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('img[src="/brands/telegram.svg"]').first()).toBeVisible()
  await expect(page.locator('img[src="/brands/whatsapp.svg"]').first()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Сводка рисков' })).toContainText('12')
})

test('analytics period and platform filters update every panel consistently', async ({ page }) => {
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.getByRole('button', { name: 'WhatsApp', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Сводка аналитики' })).toContainText('13')
  await page.getByRole('button', { name: 'Вся выборка', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Вся выборка', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.getByText('Данные графика', { exact: true }).click()
  const total = await page
    .locator('.activity-data tbody tr')
    .evaluateAll((rows) => rows.reduce((sum, row) => sum + Number(row.children[1].textContent), 0))
  expect(total).toBe(13)
  await expect(page.locator('.source-analytics-list')).not.toContainText('Финансовый рост KZ')
})

test('source graph uses labelled cards with a real path to message evidence', async ({ page }) => {
  await page.goto('/graph')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.scene-graph')).toHaveCount(0)
  await expect(page.locator('.react-flow')).toBeVisible()
  await page.getByLabel('Источник графа').selectOption('whatsapp:wa_income')
  await expect(page.locator('.react-flow__node-message')).not.toHaveCount(0)
  await page.locator('.react-flow__node-message').first().click()
  await expect(page.locator('.focus-panel')).toBeVisible()
  await page.locator('.focus-panel').getByRole('link', { name: 'Открыть проверку' }).click()
  await expect(page.getByRole('heading', { name: 'Проверка сообщения', exact: true })).toBeVisible()
})

test('activity chart exposes values through keyboard and pointer tooltips', async ({ page }) => {
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  const surface = page.locator('.activity-plot .recharts-surface')
  await surface.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('.activity-tooltip')).toContainText('Всего сообщений')
  const box = await surface.boundingBox()
  await page.mouse.move(box!.x + box!.width * 0.78, box!.y + 80)
  await expect(page.locator('.activity-tooltip')).toContainText('Высокий риск')
})

test('Enter and Space activate graph sources and message evidence', async ({ page }) => {
  await page.goto('/graph')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.locator('.react-flow__node-source').first().focus()
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Источник графа')).not.toHaveValue('')
  await page.locator('.react-flow__node-message').first().focus()
  await page.keyboard.press('Space')
  await expect(page.locator('.focus-panel')).toBeVisible()
  await expect(page.locator('.react-flow__node[data-id="root"]')).not.toHaveAttribute(
    'role',
    'button',
  )
})

test('risk summary totals open the same all-time sample', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  const link = page.getByRole('region', { name: 'Сводка рисков' }).getByRole('link').first()
  await expect(link).toHaveAttribute('href', '/?period=all&level=HIGH')
  await link.click()
  await expect(page).toHaveURL(/period=all&level=HIGH/)
})

for (const width of [375, 1440])
  test(`message graph cards remain separated at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/graph')
    await expect(page.locator('.brand-intro')).not.toBeAttached()
    await page.getByLabel('Источник графа').selectOption('whatsapp:wa_income')
    await expect(page.locator('.react-flow__node-message')).toHaveCount(3)
    const boxes = await page.locator('.react-flow__node-message').evaluateAll((nodes) =>
      nodes
        .map((node) => {
          const box = node.getBoundingClientRect()
          return { top: box.top, bottom: box.bottom }
        })
        .sort((a, b) => a.top - b.top),
    )
    for (let index = 1; index < boxes.length; index++)
      expect(boxes[index].top - boxes[index - 1].bottom).toBeGreaterThan(8)
  })

test('empty analytics has neutral zero-risk bars and an honest source empty state', async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({ mode: 'api', baseUrl: '', polling: false }),
    ),
  )
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/api/stats'
          ? {
              total_messages: 0,
              pending: 0,
              processing: 0,
              errors: 0,
              by_level: { HIGH: 0, MEDIUM: 0, LOW: 0 },
            }
          : [],
    }),
  )
  await page.goto('/analytics')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('heading', { name: 'В выборке нет сообщений' })).toBeVisible()
  const widths = await page
    .locator('.distribution-track > span')
    .evaluateAll((spans) => spans.map((span) => span.getBoundingClientRect().width))
  expect(widths).toEqual([0, 0, 0])
})
