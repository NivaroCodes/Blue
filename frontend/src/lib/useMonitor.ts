import { useCallback, useEffect, useRef, useState } from 'react'
import { getAlerts, getStats } from './api'
import { calculateStats, readStorage, writeStorage } from './model'
import type { Alert, Settings, Stats } from './model'

const defaultSettings: Settings = {
  mode: import.meta.env.VITE_DATA_MODE === 'api' ? 'api' : 'demo',
  baseUrl: import.meta.env.VITE_API_BASE_URL || '',
  polling: true,
}
function initialSettings(): Settings {
  const saved = readStorage<Settings>('blue.settings.v1', defaultSettings)
  return saved &&
    ['demo', 'api'].includes(saved.mode) &&
    typeof saved.baseUrl === 'string' &&
    typeof saved.polling === 'boolean'
    ? saved
    : defaultSettings
}
export function useMonitor() {
  const [settings, setSettings] = useState<Settings>(initialSettings)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [stats, setStats] = useState<Stats>(calculateStats([]))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)
  const [newCount, setNewCount] = useState(0)
  const [revision, setRevision] = useState(0)
  const previousIds = useRef<Set<string> | null>(null)
  const refresh = useCallback(() => setRevision((v) => v + 1), [])
  useEffect(() => {
    previousIds.current = null
    setAlerts([])
    setStats(calculateStats([]))
    setLastUpdate(null)
    setNewCount(0)
    setError('')
  }, [settings.mode, settings.baseUrl])
  useEffect(() => {
    let active = true
    let timeout: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setLoading(true)
    async function load() {
      const cycleController = new AbortController()
      try {
        const signal = AbortSignal.any([
          controller.signal,
          cycleController.signal,
          AbortSignal.timeout(12_000),
        ])
        const [data, summary] = await Promise.all([
          getAlerts(settings, signal),
          getStats(settings, signal),
        ])
        if (!active) return
        const incoming = previousIds.current
          ? data.filter((a) => !previousIds.current!.has(a.id)).length
          : 0
        if (incoming) setNewCount((v) => v + incoming)
        previousIds.current = new Set(data.map((a) => a.id))
        setAlerts(data)
        setStats(summary)
        setError('')
        setLastUpdate(new Date().toISOString())
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Не удалось загрузить сообщения.')
      } finally {
        cycleController.abort()
        if (active) {
          setLoading(false)
          if (settings.polling) timeout = setTimeout(load, 10_000)
        }
      }
    }
    void load()
    return () => {
      active = false
      controller.abort()
      clearTimeout(timeout)
    }
  }, [settings, revision])
  const updateSettings = (next: Settings) => {
    writeStorage('blue.settings.v1', next)
    setSettings(next)
  }
  const updateAlert = (alert: Alert) =>
    setAlerts((items) => items.map((a) => (a.id === alert.id ? alert : a)))
  return {
    settings,
    updateSettings,
    alerts,
    stats,
    loading,
    error,
    lastUpdate,
    newCount,
    setNewCount,
    refresh,
    updateAlert,
  }
}
export type Monitor = ReturnType<typeof useMonitor>
