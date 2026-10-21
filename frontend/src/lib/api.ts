import { z } from 'zod'
import { demoAlerts, reviewDemo } from '../data/demo'
import { AlertSchema, calculateStats, StatsSchema } from './model'
import type { Review, Settings } from './model'

async function request(settings: Settings, path: string, options: RequestInit = {}) {
  const response = await fetch(`${settings.baseUrl.replace(/\/$/, '')}/api${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
    signal: options.signal || AbortSignal.timeout(12_000),
  })
  if (!response.ok)
    throw new Error(`API вернул ${response.status}. Проверьте адрес сервера и доступ к нему.`)
  try {
    return await response.json()
  } catch {
    throw new Error('API вернул ответ, который не является JSON.')
  }
}
export async function getAlerts(settings: Settings, signal?: AbortSignal) {
  if (settings.mode === 'demo') return demoAlerts()
  const result = z
    .union([z.array(AlertSchema), z.object({ items: z.array(AlertSchema) })])
    .safeParse(await request(settings, '/alerts', { signal }))
  if (!result.success)
    throw new Error('Формат /api/alerts не соответствует контракту. Проверьте docs/API.md.')
  return Array.isArray(result.data) ? result.data : result.data.items
}
export async function getAlert(settings: Settings, id: string, signal?: AbortSignal) {
  if (settings.mode === 'demo') {
    const alert = demoAlerts().find((a) => a.id === id)
    if (!alert) throw new Error('Сообщение не найдено.')
    return alert
  }
  const result = AlertSchema.safeParse(
    await request(settings, `/alerts/${encodeURIComponent(id)}`, { signal }),
  )
  if (!result.success)
    throw new Error('Детали сообщения не соответствуют контракту API. Проверьте docs/API.md.')
  return result.data
}
export async function getStats(settings: Settings, signal?: AbortSignal) {
  if (settings.mode === 'demo') return calculateStats(demoAlerts())
  const result = StatsSchema.safeParse(await request(settings, '/stats', { signal }))
  if (!result.success)
    throw new Error('Формат /api/stats не соответствует контракту. Проверьте docs/API.md.')
  return result.data
}
export async function saveReview(
  settings: Settings,
  id: string,
  review_status: Review,
  reviewer_note: string,
) {
  if (settings.mode === 'demo') return reviewDemo(id, review_status, reviewer_note)
  const result = AlertSchema.safeParse(
    await request(settings, `/alerts/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ review_status, reviewer_note }),
    }),
  )
  if (!result.success)
    throw new Error(
      'Ответ на сохранение не соответствует контракту API. Проверьте состояние решения на сервере.',
    )
  return result.data
}
