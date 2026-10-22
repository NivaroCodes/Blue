import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDownToLine,
  ChevronLeft,
  ChevronRight,
  Filter,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Empty,
  ErrorBox,
  Platform,
  ProcessingBadge,
  ReviewBadge,
  RiskBadge,
} from '../components/ui'
import { dateTime, levelLabels, levels, time } from '../lib/model'
import type { Alert } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'

export function Dashboard({
  monitor: m,
  onDemoMessage,
}: {
  monitor: Monitor
  onDemoMessage: () => void
}) {
  const [urlParams, setUrlParams] = useSearchParams()
  const [params, setParams] = useState(urlParams)
  const paramsRef = useRef(urlParams)
  useEffect(() => {
    paramsRef.current = urlParams
    setParams(urlParams)
  }, [urlParams])
  const search = params.get('q') || '',
    level = params.get('level') || '',
    platform = params.get('platform') || '',
    chat = params.get('chat') || '',
    review = params.get('review') || '',
    period = params.get('period') || '24'
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<'latest' | 'risk'>('latest')
  const [settingsError, setSettingsError] = useState('')
  function applyParams(values: URLSearchParams | Record<string, string>) {
    const next = new URLSearchParams(values)
    paramsRef.current = next
    setParams(next)
    setUrlParams(next, { replace: true })
    setPage(1)
  }
  function filter(name: string, value: string) {
    // React Router URL updates are transitions, not queued React state updates.
    // Preserve the latest interaction even before the previous URL commits.
    const next = new URLSearchParams(paramsRef.current)
    if (value) next.set(name, value)
    else next.delete(name)
    applyParams(next)
  }
  const chats = Array.from(new Map(m.alerts.map((a) => [a.chat_id, a.chat_name])))
  const filtered = useMemo(
    () =>
      m.alerts
        .filter((a) => {
          const match = `${a.text} ${a.chat_name} ${a.id}`
            .toLocaleLowerCase()
            .includes(search.toLocaleLowerCase())
          return (
            match &&
            (!level || a.risk_level === level) &&
            (!platform || a.platform === platform) &&
            (!chat || a.chat_id === chat) &&
            (!review || a.review_status === review) &&
            (period === 'all' || Date.now() - +new Date(a.timestamp) <= Number(period) * 3_600_000)
          )
        })
        .sort((a, b) =>
          sort === 'risk'
            ? (b.risk_score ?? -1) - (a.risk_score ?? -1)
            : +new Date(b.timestamp) - +new Date(a.timestamp),
        ),
    [m.alerts, search, level, platform, chat, review, period, sort],
  )
  const maxPage = Math.max(1, Math.ceil(filtered.length / 6)),
    currentPage = Math.min(page, maxPage)
  const rows = filtered.slice((currentPage - 1) * 6, currentPage * 6)
  const filterCount = [level, platform, chat, review, search].filter(Boolean).length
  function exportData() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            exported_at: new Date().toISOString(),
            mode: m.settings.mode,
            synthetic: m.settings.mode === 'demo',
            alerts: filtered,
          },
          null,
          2,
        ),
      ],
      { type: 'application/json' },
    )
    const url = URL.createObjectURL(blob),
      anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `kraken-alerts-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function togglePolling() {
    try {
      m.updateSettings({ ...m.settings, polling: !m.settings.polling })
      setSettingsError('')
    } catch (e) {
      setSettingsError(e instanceof Error ? e.message : 'Не удалось сохранить настройку.')
    }
  }
  return (
    <>
      <div className="page-heading inbox-heading">
        <div>
          <h1>Входящие</h1>
          <p>
            {m.alerts.length} сообщений · {chats.length} источников
            <span className="new-count" aria-live="polite">
              {m.newCount > 0 ? ` · +${m.newCount} новых` : ''}
            </span>
          </p>
        </div>
        <div className="heading-actions">
          <button className="button" onClick={exportData} disabled={m.loading || !filtered.length}>
            <ArrowDownToLine size={16} /> Экспорт
          </button>
          {m.settings.mode === 'demo' && (
            <button className="button button-primary" onClick={onDemoMessage}>
              <Plus size={16} /> Демо-сообщение
            </button>
          )}
        </div>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      {settingsError && (
        <p className="form-error" role="alert">
          {settingsError}
        </p>
      )}
      <section className="inbox" aria-label="Сообщения для проверки">
        <div className="inbox-tabs" aria-label="Фильтр риска">
          <button
            aria-pressed={!level}
            className={!level ? 'selected' : ''}
            onClick={() => filter('level', '')}
          >
            Все <span>{m.alerts.length}</span>
          </button>
          {levels.map((l) => (
            <button
              key={l}
              aria-pressed={level === l}
              className={level === l ? 'selected' : ''}
              onClick={() => filter('level', l)}
            >
              <i className={`risk-tick ${l.toLowerCase()}`} />
              {levelLabels[l]}
              <span>{m.stats.by_level[l]}</span>
            </button>
          ))}
        </div>
        <div className="inbox-toolbar">
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="Поиск сообщений"
              placeholder="Поиск сообщений или источника"
              value={search}
              onChange={(e) => filter('q', e.target.value)}
            />
          </label>
          <details className="filter-disclosure">
            <summary className="button">
              <Filter size={15} /> Фильтры{' '}
              {filterCount > 0 && <span className="count-badge">{filterCount}</span>}
            </summary>
            <div className="filter-fields">
              <label>
                Платформа
                <select
                  aria-label="Платформа"
                  value={platform}
                  onChange={(e) => filter('platform', e.target.value)}
                >
                  <option value="">Все платформы</option>
                  <option value="telegram">Telegram</option>
                  <option value="whatsapp">WhatsApp</option>
                </select>
              </label>
              <label>
                Источник
                <select
                  aria-label="Чат"
                  value={chat}
                  onChange={(e) => filter('chat', e.target.value)}
                >
                  <option value="">Все чаты</option>
                  {chats.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Риск
                <select
                  aria-label="Уровень риска"
                  value={level}
                  onChange={(e) => filter('level', e.target.value)}
                >
                  <option value="">Любой риск</option>
                  {levels.map((l) => (
                    <option key={l} value={l}>
                      {levelLabels[l]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Статус
                <select
                  aria-label="Статус проверки"
                  value={review}
                  onChange={(e) => filter('review', e.target.value)}
                >
                  <option value="">Все сообщения</option>
                  <option value="NEW">На проверке</option>
                  <option value="REVIEWED">Проверенные</option>
                  <option value="FALSE_POSITIVE">Ложные срабатывания</option>
                </select>
              </label>
              <label>
                Период
                <select
                  aria-label="Период ленты"
                  value={period}
                  onChange={(e) => filter('period', e.target.value)}
                >
                  <option value="24">Последние 24 часа</option>
                  <option value="168">Последние 7 дней</option>
                  <option value="all">Всё время</option>
                </select>
              </label>
              <button className="text-button" onClick={() => applyParams({ period: 'all' })}>
                Очистить фильтры
              </button>
            </div>
          </details>
          <div className="toolbar-trailing">
            <button
              className="icon-button"
              aria-label={
                m.settings.polling ? 'Приостановить live-обновления' : 'Включить live-обновления'
              }
              aria-pressed={m.settings.polling}
              onClick={togglePolling}
            >
              {m.settings.polling ? <Pause size={16} /> : <Play size={16} />}
            </button>
            <button
              className="icon-button"
              aria-label="Обновить данные"
              onClick={m.refresh}
              disabled={m.loading}
            >
              <RefreshCw size={16} className={m.loading ? 'spin' : ''} />
            </button>
          </div>
        </div>
        {filterCount > 0 && rows.length > 0 && (
          <div className="active-filter-note">
            Найдено: {filtered.length}
            <button className="text-button" onClick={() => applyParams({ period })}>
              Сбросить фильтры
            </button>
          </div>
        )}
        {m.loading && !m.alerts.length ? (
          <div className="loading-state" role="status">
            <RefreshCw size={18} className="spin" />
            Загружаем сообщения…
          </div>
        ) : !rows.length ? (
          <Empty
            title="Сообщений не найдено"
            text={m.error ? 'Проверьте подключение.' : 'Измените запрос или сбросьте фильтры.'}
            action={
              <button className="button" onClick={() => applyParams({ period: 'all' })}>
                Сбросить фильтры
              </button>
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="alerts-table">
              <thead>
                <tr>
                  <th>Сообщение</th>
                  <th>
                    <button onClick={() => setSort(sort === 'risk' ? 'latest' : 'risk')}>
                      Риск <span aria-hidden="true">↓</span>
                    </button>
                  </th>
                  <th>Проверка</th>
                  <th>Получено</th>
                  <th>
                    <span className="sr-only">Открыть</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="table-footer">
          <span>
            {filtered.length
              ? `${(currentPage - 1) * 6 + 1}–${Math.min(currentPage * 6, filtered.length)} из ${filtered.length}`
              : '0 сообщений'}
          </span>
          <div className="pagination">
            <button
              className="icon-button"
              aria-label="Предыдущая страница"
              disabled={currentPage === 1}
              onClick={() => setPage(currentPage - 1)}
            >
              <ChevronLeft size={16} />
            </button>
            {Array.from({ length: maxPage }, (_, i) => i + 1)
              .filter((i) => i === 1 || i === maxPage || Math.abs(i - currentPage) < 2)
              .map((n, i, arr) => (
                <span key={n}>
                  {i > 0 && n - arr[i - 1] > 1 && <span className="pagination-ellipsis">…</span>}
                  <button
                    aria-label={`Страница ${n}`}
                    aria-current={n === currentPage ? 'page' : undefined}
                    className={n === currentPage ? 'selected' : ''}
                    onClick={() => setPage(n)}
                  >
                    {n}
                  </button>
                </span>
              ))}
            <button
              className="icon-button"
              aria-label="Следующая страница"
              disabled={currentPage === maxPage}
              onClick={() => setPage(currentPage + 1)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </section>
      <div className="connection-line">
        <span>
          <i className={`status-dot ${m.error ? 'is-error' : ''}`} />
          {m.error
            ? 'Связь прервана'
            : m.settings.polling
              ? 'Автообновление каждые 10 с'
              : 'Обновление на паузе'}
        </span>
        <span>
          {m.lastUpdate ? `Обновлено в ${time(m.lastUpdate)} · UTC+5` : 'Ожидание данных'}
        </span>
      </div>
    </>
  )
}
function AlertRow({ alert: a }: { alert: Alert }) {
  return (
    <tr>
      <td>
        <div className="message-cell">
          <Platform platform={a.platform} />
          <div className="message-cell-text">
            <div className="message-source">
              <b>{a.chat_name}</b>
              <span>{a.platform === 'telegram' ? 'Telegram' : 'WhatsApp'}</span>
            </div>
            <Link className="message-preview" to={`/alerts/${encodeURIComponent(a.id)}`}>
              {a.text}
            </Link>
            {a.status !== 'PROCESSED' && <ProcessingBadge status={a.status} />}
          </div>
        </div>
      </td>
      <td>
        <RiskBadge level={a.risk_level} score={a.risk_score} />
      </td>
      <td>
        <ReviewBadge status={a.review_status} />
      </td>
      <td className="date-cell">
        <b>{time(a.timestamp)}</b>
        <span>{dateTime(a.timestamp).split(',')[0]}</span>
      </td>
      <td>
        <Link
          className="row-open"
          aria-label={`Открыть сообщение ${a.id}`}
          to={`/alerts/${encodeURIComponent(a.id)}`}
        >
          <ChevronRight size={17} />
        </Link>
      </td>
    </tr>
  )
}
