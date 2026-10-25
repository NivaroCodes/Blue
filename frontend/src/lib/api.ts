import { z } from 'zod'
import { demoAlerts, reviewDemo } from '../data/demo'
import { AlertSchema, calculateStats, StatsSchema } from './model'
import { getAccessToken } from './auth'
import type { Review, Settings } from './model'

async function request(settings: Settings, path: string, options: RequestInit = {}) {
  if (settings.baseUrl) {
    try {
      const url = new URL(settings.baseUrl)
      if (
        !['http:', 'https:'].includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash
      )
        throw new Error()
    } catch {
      throw new Error('Подключение к сервису данных не настроено. Обратитесь к команде проекта.')
    }
  }
  async function send(token: string | null) {
    return fetch(`${settings.baseUrl.replace(/\/$/, '')}/api${path}`, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
      signal: options.signal || AbortSignal.timeout(12_000),
    })
  }
  let response = await send(await getAccessToken())
  if (response.status === 401) {
    const refreshedToken = await getAccessToken(true)
    if (refreshedToken) response = await send(refreshedToken)
  }
  if (!response.ok)
    throw new Error(response.status === 401
      ? 'Сессия завершилась. Войдите снова, чтобы продолжить.'
      : `API вернул ${response.status}. Проверьте адрес сервера и доступ к нему.`)
  try {
    return await response.json()
  } catch {
    throw new Error('Не удалось прочитать данные сервиса. Попробуйте обновить сообщения.')
  }
}
export async function getAlerts(settings: Settings, signal?: AbortSignal) {
  if (settings.mode === 'demo') return demoAlerts()
  const result = z
    .union([z.array(AlertSchema), z.object({ items: z.array(AlertSchema) })])
    .safeParse(await request(settings, '/alerts', { signal }))
  if (!result.success)
    throw new Error('Сервис вернул неполные данные сообщений. Попробуйте обновить выборку.')
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
    throw new Error('Сервис вернул неполные данные сообщения. Попробуйте открыть его позже.')
  return result.data
}
export async function getStats(settings: Settings, signal?: AbortSignal) {
  if (settings.mode === 'demo') return calculateStats(demoAlerts())
  const result = StatsSchema.safeParse(await request(settings, '/stats', { signal }))
  if (!result.success)
    throw new Error('Не удалось получить сводку сообщений. Попробуйте обновить выборку.')
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
      'Не удалось подтвердить сохранение решения. Обновите сообщение и проверьте его статус.',
    )
  return result.data
}
