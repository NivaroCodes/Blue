import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  CheckCircle2,
  CircleAlert,
  Database,
  FlaskConical,
  Globe,
  Plug,
  RefreshCw,
  Save,
} from 'lucide-react'
import { getStats } from '../lib/api'
import type { Settings } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'
import { Panel } from '../components/ui'

export function SettingsPage({
  monitor: m,
  notify,
}: {
  monitor: Monitor
  notify: (s: string) => void
}) {
  const [draft, setDraft] = useState<Settings>(m.settings)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState('')
  function validate(): Settings | null {
    const baseUrl = draft.baseUrl.trim().replace(/\/$/, '')
    if (baseUrl) {
      try {
        const url = new URL(baseUrl)
        if (
          !['http:', 'https:'].includes(url.protocol) ||
          url.search ||
          url.hash ||
          url.username ||
          url.password ||
          /\/api$/.test(url.pathname)
        )
          throw new Error()
      } catch {
        setError(
          'Укажите HTTP(S)-адрес сервера без /api, query-параметров и учётных данных. Например: http://127.0.0.1:8000',
        )
        return null
      }
    }
    setError('')
    return { ...draft, baseUrl }
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next = validate()
    if (!next) return
    try {
      m.updateSettings(next)
      setDraft(next)
      notify('Настройки сохранены. Источник данных обновлён.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить настройки.')
    }
  }
  async function check() {
    const next = validate()
    if (!next) return
    setChecking(true)
    setResult('')
    try {
      const stats = await getStats({ ...next, mode: 'api' })
      setResult(
        `Подключение работает. API сообщает: ${stats.total_messages} сообщений. Нажмите «Сохранить», чтобы использовать этот сервер.`,
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Сервер недоступен. Проверьте адрес и CORS.')
    } finally {
      setChecking(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Настройки</h1>
          <p>Источник данных и обновление сообщений.</p>
        </div>
      </div>
      <div className="settings-grid">
        <div>
          <Panel title="Источник данных" description="Выберите режим работы Blue">
            <form className="settings-form" onSubmit={save}>
              <fieldset className="mode-options">
                <legend className="sr-only">Режим данных</legend>
                <label className={draft.mode === 'demo' ? 'mode-card selected' : 'mode-card'}>
                  <span className="mode-icon">
                    <FlaskConical size={22} />
                  </span>
                  <div>
                    <b>Демонстрация</b>
                    <p>
                      Синтетические сообщения и заранее заданные оценки. Можно проверять без
                      backend.
                    </p>
                  </div>
                  <input
                    type="radio"
                    name="mode"
                    value="demo"
                    checked={draft.mode === 'demo'}
                    onChange={() => setDraft({ ...draft, mode: 'demo' })}
                  />
                </label>
                <label className={draft.mode === 'api' ? 'mode-card selected' : 'mode-card'}>
                  <span className="mode-icon">
                    <Database size={22} />
                  </span>
                  <div>
                    <b>Backend API</b>
                    <p>Сообщения, результаты анализа и решения аналитика из API команды.</p>
                  </div>
                  <input
                    type="radio"
                    name="mode"
                    value="api"
                    checked={draft.mode === 'api'}
                    onChange={() => setDraft({ ...draft, mode: 'api' })}
                  />
                </label>
              </fieldset>
              <div className="settings-field">
                <label htmlFor="api-url">
                  <Globe size={15} /> Адрес Backend API
                </label>
                <input
                  id="api-url"
                  type="text"
                  inputMode="url"
                  value={draft.baseUrl}
                  onChange={(e) => {
                    setDraft({ ...draft, baseUrl: e.target.value })
                    setResult('')
                  }}
                  placeholder="http://127.0.0.1:8000"
                  aria-describedby="api-help"
                  aria-invalid={!!error}
                />
                <p id="api-help">
                  Укажите адрес без <code>/api</code>. Пустое поле использует текущий домен и прокси
                  Vite на порт 8000.
                </p>
                <button type="button" className="button" disabled={checking} onClick={check}>
                  {checking ? <RefreshCw size={16} className="spin" /> : <Plug size={16} />}
                  {checking ? 'Проверяем…' : 'Проверить API'}
                </button>
              </div>
              <div className="polling-setting">
                <div>
                  <b>Live-обновление</b>
                  <p>
                    Новые сообщения каждые 10 секунд. Следующий запрос начинается после завершения
                    предыдущего.
                  </p>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    aria-label="Live-обновление"
                    checked={draft.polling}
                    onChange={(e) => setDraft({ ...draft, polling: e.target.checked })}
                  />
                  <span />
                </label>
              </div>
              {error && (
                <p className="form-error" role="alert">
                  <CircleAlert size={16} /> {error}
                </p>
              )}
              {result && (
                <p className="form-success" role="status">
                  <CheckCircle2 size={18} />
                  {result}
                </p>
              )}
              <div className="settings-save">
                <span>Настройки сохраняются в этом браузере.</span>
                <button className="button button-primary" disabled={checking}>
                  <Save size={16} /> Сохранить
                </button>
              </div>
            </form>
          </Panel>
        </div>
      </div>
    </>
  )
}
