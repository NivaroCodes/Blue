import { expect, test } from '@playwright/test'
import {
  activityBins,
  reasonSummaries,
  selectAnalytics,
  sourceSummaries,
} from '../src/lib/analytics'
import { demoAlerts } from '../src/data/demo'
import { calculateStats } from '../src/lib/model'

test('timeline includes exact window boundaries once and excludes future and stale records', () => {
  const now = Date.parse('2026-10-23T10:35:00+05:00')
  const sample = demoAlerts()[0]
  const items = [0, -24 * 3600000, -24 * 3600000 - 1, 1].map((offset, index) => ({
    ...sample,
    id: String(index),
    timestamp: new Date(now + offset).toISOString(),
  }))
  const selected = selectAnalytics(items, '24', 'all', now)
  expect(selected.map((item) => item.id)).toEqual(['0', '1'])
  const bins = activityBins(items, '24', now)
  expect(bins.reduce((sum, bin) => sum + bin.total, 0)).toBe(2)
  expect(bins.reduce((sum, bin) => sum + bin.high, 0)).toBe(2)
  expect(bins.every((bin) => bin.high <= bin.total)).toBe(true)
})

test('filtered source totals reconcile with stats and repeated reason codes count once', () => {
  const items = demoAlerts()
  const selected = selectAnalytics(items, 'all', 'whatsapp', Date.now() + 100)
  expect(sourceSummaries(selected).reduce((sum, group) => sum + group.count, 0)).toBe(
    selected.length,
  )
  expect(calculateStats(selected).total_messages).toBe(selected.length)
  const duplicate = { ...items[0], reasons: [items[0].reasons[0], items[0].reasons[0]] }
  expect(reasonSummaries([duplicate])).toEqual([[duplicate.reasons[0].code, 1]])
})

test('empty and multi-year samples have finite bounded bins and preserve exact totals', () => {
  const now = Date.parse('2026-10-23T10:35:00+05:00')
  expect(activityBins([], 'all', now).every((bin) => bin.total === 0)).toBe(true)
  const items = ['2000-01-01T00:00:00Z', '2026-10-23T05:35:00Z'].map((timestamp, index) => ({
    ...demoAlerts()[0],
    id: String(index),
    timestamp,
  }))
  const bins = activityBins(items, 'all', now)
  expect(bins.length).toBeLessThanOrEqual(38)
  expect(bins.reduce((sum, bin) => sum + bin.total, 0)).toBe(2)
})
