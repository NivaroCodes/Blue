import { expect, test } from './fixtures'

test('entrance appears on reload even with an old saved flag, but not on SPA navigation', async ({
  page,
}) => {
  await page.addInitScript(() => sessionStorage.setItem('kraken.intro.seen.v1', '1'))
  await page.goto('/')
  const intro = page.getByRole('dialog', { name: 'Blue', exact: true })
  await expect(intro).toBeVisible()
  await expect(page.getByRole('button', { name: 'Пропустить' })).toBeFocused()
  await expect(intro).not.toBeAttached()
  await expect(page.locator('main')).toBeFocused()
  await page.reload()
  await expect(intro).toBeVisible()
  await page.getByRole('button', { name: 'Пропустить' }).click()
  await page.getByRole('link', { name: 'Чаты и источники' }).click()
  await expect(page.locator('.chat-card')).toHaveCount(5)
  await expect(intro).not.toBeAttached()
})

test('skip, keyboard dismissal and replay restore focus', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Пропустить' }).click()
  await page.getByRole('button', { name: 'О проекте' }).click()
  await page.getByRole('button', { name: 'Посмотреть заставку' }).click()
  await expect(page.getByRole('dialog', { name: 'Blue', exact: true })).toBeVisible()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Пропустить' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.locator('.brand-intro')).not.toBeAttached()
  await expect(page.getByRole('button', { name: 'О проекте' })).toBeFocused()
})

test('reduced motion has no movement and releases the workspace promptly', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('.brand-intro')).not.toBeAttached({ timeout: 3000 })
  await expect(page.getByRole('heading', { name: 'Входящие', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Экспорт', exact: true })).toBeVisible()
})
