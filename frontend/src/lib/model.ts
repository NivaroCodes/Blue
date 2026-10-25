import { z } from 'zod'

export const levels = ['HIGH', 'MEDIUM', 'LOW'] as const
export const levelLabels = { HIGH: 'Высокий', MEDIUM: 'Средний', LOW: 'Низкий' }
export const reviewLabels = {
  NEW: 'На проверке',
  REVIEWED: 'Проверено',
  FALSE_POSITIVE: 'Ложное срабатывание',
}
export const statusLabels = {
  PENDING: 'В очереди',
  PROCESSING: 'Анализируется',
  PROCESSED: 'Обработано',
  ERROR: 'Ошибка анализа',
}
export const reasonLabels: Record<string, string> = {
  UNREALISTIC_RETURN: 'Нереалистичная доходность',
  MONEY_REQUEST: 'Запрос вложений',
  REFERRAL: 'Привлечение участников',
  URGENCY: 'Давление и срочность',
  PERSONAL_TRANSFER: 'Перевод на личную карту',
  GUARANTEED_PROFIT: 'Гарантия прибыли',
}
export const AlertSchema = z
  .object({
    id: z.string(),
    platform: z.enum(['telegram', 'whatsapp']),
    chat_id: z.string(),
    chat_name: z.string(),
    message_id: z.string(),
    sender_hash: z.string(),
    text: z.string(),
    image_url: z.string().nullable().optional(),
    timestamp: z.iso.datetime({ offset: true }),
    status: z.enum(['PENDING', 'PROCESSING', 'PROCESSED', 'ERROR']),
    risk_score: z.number().min(0).max(100).nullable().default(null),
    risk_level: z.enum(levels).nullable().default(null),
    reasons: z.array(z.object({ code: z.string(), evidence: z.string() })).default([]),
    explanation: z.string().default(''),
    confidence: z.number().min(0).max(1).nullable().default(null),
    review_status: z.enum(['NEW', 'REVIEWED', 'FALSE_POSITIVE']).default('NEW'),
    reviewer_note: z.string().default(''),
    model_version: z.string().default('Не указана'),
  })
  .superRefine((value, ctx) => {
    if (value.status === 'PROCESSED' && (value.risk_score === null || value.risk_level === null))
      ctx.addIssue({ code: 'custom', message: 'Processed messages must include score and level' })
  })
export type Alert = z.infer<typeof AlertSchema>
export type Level = (typeof levels)[number]
export type Review = Alert['review_status']
export type Settings = { mode: 'demo' | 'api'; baseUrl: string; polling: boolean }
export const StatsSchema = z.object({
  total_messages: z.number().int().nonnegative(),
  pending: z.number().int().nonnegative(),
  processing: z.number().int().nonnegative(),
  errors: z.number().int().nonnegative(),
  by_level: z.object({
    HIGH: z.number().int().nonnegative(),
    MEDIUM: z.number().int().nonnegative(),
    LOW: z.number().int().nonnegative(),
  }),
})
export type Stats = z.infer<typeof StatsSchema>
export function calculateStats(alerts: Alert[]): Stats {
  return {
    total_messages: alerts.length,
    pending: alerts.filter((a) => a.status === 'PENDING').length,
    processing: alerts.filter((a) => a.status === 'PROCESSING').length,
    errors: alerts.filter((a) => a.status === 'ERROR').length,
    by_level: Object.fromEntries(
      levels.map((level) => [
        level,
        alerts.filter((a) => a.status === 'PROCESSED' && a.risk_level === level).length,
      ]),
    ) as Stats['by_level'],
  }
}
export function readStorage<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch {
    return fallback
  }
}
export function writeStorage(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    throw new Error('Браузер не разрешает сохранять данные. Разрешите локальное хранилище.')
  }
}
export const dateTime = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Qyzylorda',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
export const time = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Qyzylorda',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
