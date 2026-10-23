import { calculateStats } from './model'
import type { Alert } from './model'

export type Period = '24' | '168' | 'all'
export type PlatformFilter = 'all' | Alert['platform']
const hour = 3_600_000
const clock = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Qyzylorda',
  hour: '2-digit',
  minute: '2-digit',
})
const dateClock = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Qyzylorda',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

export function selectAnalytics(
  alerts: Alert[],
  period: Period,
  platform: PlatformFilter,
  now: number,
) {
  const from = period === 'all' ? -Infinity : now - Number(period) * hour
  return alerts.filter((alert) => {
    const timestamp = Date.parse(alert.timestamp)
    return (
      Number.isFinite(timestamp) &&
      timestamp >= from &&
      timestamp <= now &&
      (platform === 'all' || platform === alert.platform)
    )
  })
}

export function activityBins(alerts: Alert[], period: Period, now: number) {
  const selected = selectAnalytics(alerts, period, 'all', now)
  const from =
    period === 'all'
      ? selected.reduce(
          (oldest, alert) => Math.min(oldest, Date.parse(alert.timestamp)),
          selected.length ? now : now - 24 * hour,
        )
      : now - Number(period) * hour
  const desiredInterval = (now - from) / 36
  const interval =
    [hour, 6 * hour, 24 * hour, 7 * 24 * hour, 30 * 24 * hour, 365 * 24 * hour].find(
      (value) => value >= desiredInterval,
    ) || Math.ceil(desiredInterval / hour) * hour
  const start = Math.floor(from / interval) * interval
  const count = Math.max(1, Math.floor((now - start) / interval) + 1)
  const bins = Array.from({ length: count }, (_, index) => {
    const time = start + index * interval
    return {
      key: time,
      label: period === '24' ? clock.format(time) : dateClock.format(time),
      interval: `${dateClock.format(Math.max(time, from))} — ${dateClock.format(Math.min(time + interval, now))}`,
      total: 0,
      high: 0,
    }
  })
  for (const alert of selected) {
    const index = Math.floor((Date.parse(alert.timestamp) - start) / interval)
    const bin = bins[index]
    if (bin) {
      bin.total++
      if (alert.status === 'PROCESSED' && alert.risk_level === 'HIGH') bin.high++
    }
  }
  return bins
}

export function sourceSummaries(alerts: Alert[]) {
  const groups = new Map<string, Alert[]>()
  for (const alert of alerts) {
    const group = groups.get(alert.chat_id)
    if (group) group.push(alert)
    else groups.set(alert.chat_id, [alert])
  }
  return [...groups]
    .map(([id, messages]) => ({
      id,
      name: messages[0].chat_name,
      platform: messages[0].platform,
      stats: calculateStats(messages),
      count: messages.length,
      messages,
    }))
    .sort(
      (a, b) =>
        b.stats.by_level.HIGH - a.stats.by_level.HIGH ||
        b.count - a.count ||
        a.name.localeCompare(b.name),
    )
}

export function reasonSummaries(alerts: Alert[]) {
  const counts = new Map<string, number>()
  for (const alert of alerts.filter((alert) => alert.status === 'PROCESSED')) {
    for (const code of new Set(alert.reasons.map((reason) => reason.code)))
      counts.set(code, (counts.get(code) || 0) + 1)
  }
  return [...counts].sort((a, b) => b[1] - a[1])
}
