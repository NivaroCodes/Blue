import { expect, test } from '@playwright/test'

test.skip(
  process.env.BLUE_SYNTHETIC_E2E !== '1',
  'Requires a seeded API, worker and real Gemini; no mocks.',
)

test('synthetic pipeline retains its records and images but working UI excludes them', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/alerts')
  expect(response.ok()).toBeTruthy()
  const records = await response.json()
  const synthetic = records.filter(
    (a: { chat_id: string }) => a.chat_id === 'blue_demo_synthetic_v1',
  )
  expect(synthetic).toHaveLength(36)
  expect(new Set(synthetic.map((a: { id: string }) => a.id)).size).toBe(36)
  expect(synthetic.every((a: { status: string }) => a.status === 'PROCESSED')).toBeTruthy()
  const images = synthetic.filter((a: { image_url?: string }) => a.image_url)
  expect(images).toHaveLength(3)
  for (const image of images) {
    expect(image.image_analyzed).toBe(true)
    expect((await request.get(image.image_url)).ok()).toBeTruthy()
  }
  await page.addInitScript(() =>
    localStorage.setItem(
      'blue.settings.v1',
      JSON.stringify({
        mode: 'api',
        baseUrl: '',
        polling: false,
      }),
    ),
  )
  await page.goto('/')
  await expect(page.locator('.source-pill')).toHaveText('Рабочие данные')
  const workingCount = records.filter(
    (a: { chat_id: string }) => a.chat_id !== 'blue_demo_synthetic_v1',
  ).length
  await expect(page.locator('.inbox-title')).toContainText(`${workingCount} сообщений`)
  await expect(page.locator('main')).not.toContainText('Blue Demo — Synthetic Chat')
  const poster = images.find((a: { message_id: string }) => a.message_id === 'synthetic-v1-036')
  expect(poster).toBeTruthy()
  await page.goto(`/alerts/${poster.id}`)
  await expect(page.getByRole('alert')).toContainText('Синтетическое сообщение недоступно')
  await expect(page.locator('.original-message')).toHaveCount(0)
  await expect(page.getByRole('img', { name: 'Изображение из исходного сообщения' })).toHaveCount(0)
  if (process.env.BLUE_SCREENSHOT_PATH)
    await page.screenshot({ path: process.env.BLUE_SCREENSHOT_PATH, fullPage: true })
})
