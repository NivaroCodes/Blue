import { expect, test } from '@playwright/test'

test('Kraken intro completes, restores access and stays dismissed in this tab', async ({
  page,
}) => {
  await page.goto('/')
  const intro = page.getByRole('dialog', { name: 'Kraken', exact: true })
  await expect(intro).toBeVisible()
  await expect(page.getByRole('button', { name: 'Пропустить' })).toBeFocused()
  await expect(intro).not.toBeAttached({ timeout: 6000 })
  await expect(page.locator('main')).toBeFocused()
  await expect(page).toHaveTitle('Kraken — Мониторинг рисков')
  await page.reload()
  await expect(intro).not.toBeAttached()
  await page.getByRole('link', { name: 'Чаты и источники' }).click()
  await expect(page.locator('.chat-card')).toHaveCount(5)
  await expect(intro).not.toBeAttached()
})

test('intro can be skipped, replayed and dismissed by keyboard', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Пропустить' }).click()
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await page.getByRole('button', { name: 'О проекте' }).click()
  await page.getByRole('button', { name: 'Посмотреть заставку' }).click()
  await expect(page.getByRole('dialog', { name: 'Kraken', exact: true })).toBeVisible()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Пропустить' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('button', { name: 'О проекте' })).toBeFocused()
})

test('reduced motion opens the workspace immediately', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('button', { name: 'Экспорт', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'О проекте' }).click()
  await page.getByRole('button', { name: 'Посмотреть заставку' }).click()
  await expect(page.locator('.brand-intro')).toHaveCSS('animation-name', 'none')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
})
