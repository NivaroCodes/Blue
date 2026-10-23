import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
})

test('Blue evidence preview follows selection and filters', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page).toHaveTitle(/Blue/)
  await expect(page.getByRole('link', { name: 'Blue — мониторинг' })).toBeVisible()
  const previews = page.getByRole('button', { name: /Предпросмотр сообщения/ })
  await previews.nth(1).click()
  const previewName = (await previews.nth(1).getAttribute('aria-label'))!
  const sourceName = await previews.nth(1).textContent()
  expect(previewName).toContain(sourceName)
  const id = previewName.replace('Предпросмотр сообщения ', '').split(': ')[0]
  await expect(page.locator('.focus-panel')).toHaveAttribute('data-alert-id', id)
  await expect(
    page.locator('.focus-panel').getByRole('link', { name: 'Открыть проверку' }),
  ).toHaveAttribute('href', `/alerts/${id}`)
  await page.getByLabel('Поиск сообщений').fill('zz-no-match-zz')
  await expect(page.locator('.focus-panel')).toContainText('Выберите сообщение')
})

test('graph shows actual membership and remains usable without WebGL', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type.includes('webgl')) return null
      return original.call(this, type as '2d', ...(args as []))
    } as typeof original
  })
  await page.goto('/graph')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('heading', { name: 'Граф связей', exact: true })).toBeVisible()
  await expect(
    page.getByText('Связь означает принадлежность к источнику, а не участие в схеме.'),
  ).toBeVisible()
  const select = page.getByLabel('Источник графа')
  await expect(select.locator('option')).toHaveCount(6)
  await select.selectOption('wa_income')
  await expect(page.locator('.graph-message-list a')).not.toHaveCount(0)
  const href = await page.locator('.graph-message-list a').first().getAttribute('href')
  await page.locator('.graph-message-list a').first().click()
  await expect(page).toHaveURL(new RegExp(`${href}$`))
  await expect(page.getByRole('heading', { name: 'Проверка сообщения', exact: true })).toBeVisible()
})

test('unchanged polling snapshot preserves the interactive graph view', async ({ page }) => {
  await page.goto('/graph')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.locator('.react-flow__viewport')).toBeVisible()
  await page.locator('.react-flow__viewport').evaluate((element) => {
    element.setAttribute('data-view-marker', 'zoomed')
  })
  await page.getByRole('button', { name: 'Приблизить', exact: true }).click()
  const transform = await page.locator('.react-flow__viewport').getAttribute('style')
  await page.waitForTimeout(11_000)
  await expect(page.locator('.react-flow__viewport')).toHaveAttribute('data-view-marker', 'zoomed')
  await expect(page.locator('.react-flow__viewport')).toHaveAttribute('style', transform!)
})
