import { useState } from 'react'
import { Check, CircleAlert, Database, FlaskConical, RefreshCw, Save, Wifi } from 'lucide-react'
import { getStats } from '../lib/api'
import type { Monitor } from '../lib/useMonitor'

export function SettingsPage({
  monitor: m,
  notify,
}: {
  monitor: Monitor
  notify: (s: string) => void
}) {
  const [draft, setDraft] = useState(m.settings)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState('')
  async function check() {
    setChecking(true)
    setError('')
    setResult('')
    try {
      await getStats({ ...draft, mode: 'api' })
      setResult('Подключение работает. Данные доступны для мониторинга.')
    } catch {
      setError(
        'Не удалось связаться с сервисом данных. Попробуйте позже или обратитесь к команде проекта.',
      )
    } finally {
      setChecking(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Настройки</h1>
          <p>Выберите данные и настройте обновление рабочего пространства.</p>
        </div>
      </div>
      <form
        className="workspace-settings"
        onSubmit={(event) => {
          event.preventDefault()
          try {
            m.updateSettings(draft)
            setError('')
            notify('Настройки сохранены. Источник данных обновлён.')
          } catch {
            setError('Не удалось сохранить настройки в браузере.')
          }
        }}
      >
        <section className="settings-section">
          <div>
            <h2>Источник данных</h2>
            <p>
              Демонстрация помогает изучить интерфейс. Рабочие данные поступают из подключённого
              сервиса.
            </p>
          </div>
          <fieldset className="data-mode-options">
            <legend className="sr-only">Режим данных</legend>
            {(
              [
                {
                  mode: 'demo',
                  title: 'Демонстрационные данные',
                  text: 'Синтетические примеры для презентации и проверки сценариев.',
                  Icon: FlaskConical,
                },
                {
                  mode: 'api',
                  title: 'Рабочие данные',
                  text: 'Сообщения и результаты анализа, поступающие от команды.',
                  Icon: Database,
                },
              ] as const
            ).map(({ mode, title, text, Icon }) => (
              <label key={mode} className={draft.mode === mode ? 'chosen' : ''}>
                <Icon size={21} />
                <div>
                  <strong>{title}</strong>
                  <p>{text}</p>
                </div>
                <input
                  type="radio"
                  name="mode"
                  value={mode}
                  checked={draft.mode === mode}
                  onChange={() => setDraft({ ...draft, mode })}
                />
              </label>
            ))}
          </fieldset>
        </section>
        <section className="settings-section">
          <div>
            <h2>Подключение</h2>
            <p>Проверьте, доступен ли сервис рабочих данных.</p>
          </div>
          <div className="service-connection">
            <Wifi size={20} />
            <div>
              <strong>Сервис мониторинга</strong>
              <p>{result || 'Проверка не меняет выбранный режим.'}</p>
            </div>
            <button type="button" className="button" onClick={check} disabled={checking}>
              {checking ? <RefreshCw size={15} className="spin" /> : <Check size={15} />}{' '}
              {checking ? 'Проверяем…' : 'Проверить подключение'}
            </button>
          </div>
        </section>
        <section className="settings-section">
          <div>
            <h2>Обновление сообщений</h2>
            <p>Поддерживайте очередь актуальной во время проверки.</p>
          </div>
          <div className="settings-polling">
            <div>
              <strong>Автоматическое обновление</strong>
              <p>Новые данные каждые 10 секунд. Очередь остаётся доступной во время обновления.</p>
            </div>
            <label className="switch">
              <input
                type="checkbox"
                aria-label="Live-обновление"
                checked={draft.polling}
                onChange={(event) => setDraft({ ...draft, polling: event.target.checked })}
              />
              <span />
            </label>
          </div>
        </section>
        {error && (
          <p className="form-error" role="alert">
            <CircleAlert size={16} /> {error}
          </p>
        )}
        {result && (
          <p className="form-success" role="status">
            {result}
          </p>
        )}
        <div className="settings-save">
          <span>Настройки сохраняются в этом браузере.</span>
          <button className="button button-primary" disabled={checking}>
            <Save size={16} />
            Сохранить
          </button>
        </div>
      </form>
    </>
  )
}
