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
import { EvidencePreview } from '../components/EvidencePreview'
import { RiskSummary } from '../components/RiskSummary'
import { saveVisibility } from '../lib/api'
import { dateTime, levelLabels, levels, time } from '../lib/model'
import type { Alert } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'
import { selectAnalytics, sourceSummaries } from '../lib/analytics'
import type { Period, PlatformFilter } from '../lib/analytics'

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
    offTopicView = params.get('view') === 'off_topic',
    period = params.get('period') || (offTopicView ? 'all' : '24')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<'latest' | 'risk'>('latest')
  const [settingsError, setSettingsError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [changingId, setChangingId] = useState('')
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
    if (name === 'platform') next.delete('chat')
    if (name === 'view') next.delete('level')
    applyParams(next)
  }
  const hiddenCount = m.alerts.filter((a) => a.status === 'OFF_TOPIC').length
  const viewAlerts = m.alerts.filter((a) => offTopicView ? a.status === 'OFF_TOPIC' : a.status !== 'OFF_TOPIC')
  const chats = sourceSummaries(viewAlerts).filter((source) => !platform || source.platform === platform)
  const matchingChats = chats.filter((source) => source.id === chat)
  const selectedChat = matchingChats.length === 1 ? matchingChats[0].key : ''
  const snapshotTime = m.lastUpdate ? Date.parse(m.lastUpdate) : Date.now()
  const filtered = useMemo(
    () =>
      selectAnalytics(viewAlerts, period as Period, (platform || 'all') as PlatformFilter, snapshotTime)
        .filter((a) => {
          const match = `${a.text} ${a.chat_name} ${a.id}`
            .toLocaleLowerCase()
            .includes(search.toLocaleLowerCase())
          return (
            match &&
            (!level || a.risk_level === level) &&
            (!chat || a.chat_id === chat) &&
            (!review || a.review_status === review)
          )
        })
        .sort((a, b) =>
          sort === 'risk'
            ? (b.risk_score ?? -1) - (a.risk_score ?? -1)
            : +new Date(b.timestamp) - +new Date(a.timestamp),
        ),
    [m.alerts, offTopicView, search, level, platform, chat, review, period, sort, snapshotTime],
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
    anchor.download = `blue-alerts-${new Date().toISOString().slice(0, 10)}.json`
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
  async function changeVisibility(alert: Alert) {
    if (m.settings.mode !== 'api' || changingId) return
    const restore = alert.status === 'OFF_TOPIC'
    if (!restore && !window.confirm('Скрыть это сообщение из основной очереди? Его можно будет восстановить.')) return
    setChangingId(alert.id)
    setSettingsError('')
    try {
      m.updateAlert(await saveVisibility(m.settings, alert.id, !restore))
    } catch (e) {
      setSettingsError(e instanceof Error ? e.message : 'Не удалось изменить видимость сообщения.')
    } finally {
      setChangingId('')
    }
  }
  return (
    <>
      <div className="page-heading inbox-heading">
        <div>
          <h1>Мониторинг сообщений</h1>
          <p>
            Проверяйте предупреждения из Telegram и WhatsApp.
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
      <RiskSummary stats={m.stats} />
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      {settingsError && (
        <p className="form-error" role="alert">
          {settingsError}
        </p>
      )}
      <div className="inbox-layout">
        <section className="inbox" aria-label={offTopicView ? 'Нерелевантные сообщения' : 'Сообщения для проверки'}>
          <div className="inbox-title">
            <h2>{offTopicView ? 'Нерелевантные сообщения' : 'Входящие'}</h2>
            <span>
              {viewAlerts.length} сообщений · {chats.length} источников
            </span>
          </div>
          <div className="inbox-tabs" aria-label="Фильтр риска">
            <button
              aria-pressed={!level}
              className={!level ? 'selected' : ''}
              onClick={() => filter('level', '')}
            >
              Все <span>{viewAlerts.length}</span>
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
                <span>{viewAlerts.filter((a) => a.risk_level === l).length}</span>
              </button>
            ))}
            <button
              aria-pressed={offTopicView}
              className={offTopicView ? 'selected' : ''}
              onClick={() => filter('view', offTopicView ? '' : 'off_topic')}
            >
              Нерелевантные <span>{hiddenCount}</span>
            </button>
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
                    value={selectedChat}
                    onChange={(e) => {
                      const source = chats.find((item) => item.key === e.target.value)
                      const next = new URLSearchParams(paramsRef.current)
                      if (source) {
                        next.set('chat', source.id)
                        next.set('platform', source.platform)
                      } else next.delete('chat')
                      applyParams(next)
                    }}
                  >
                    <option value="">Все чаты</option>
                    {chats.map((source) => (
                      <option key={source.key} value={source.key}>
                        {source.name} · {source.platform === 'telegram' ? 'Telegram' : 'WhatsApp'}
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
                <button className="text-button" onClick={() => applyParams({ period: 'all', ...(offTopicView ? { view: 'off_topic' } : {}) })}>
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
              <button className="text-button" onClick={() => applyParams({ period, ...(offTopicView ? { view: 'off_topic' } : {}) })}>
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
                <button className="button" onClick={() => applyParams({ period: 'all', ...(offTopicView ? { view: 'off_topic' } : {}) })}>
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
                    <AlertRow
                      key={alert.id}
                      alert={alert}
                      selected={
                        alert.id === (rows.find((row) => row.id === selectedId) || rows[0])?.id
                      }
                      onSelect={() => setSelectedId(alert.id)}
                      onVisibilityChange={() => void changeVisibility(alert)}
                      visibilityBusy={changingId === alert.id}
                      canChangeVisibility={m.settings.mode === 'api'}
                    />
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
        <EvidencePreview
          alert={rows.find((alert) => alert.id === selectedId) || rows[0]}
          demo={m.settings.mode === 'demo'}
          settings={m.settings}
        />
      </div>
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
function AlertRow({
  alert: a,
  selected,
  onSelect,
  onVisibilityChange,
  visibilityBusy,
  canChangeVisibility,
}: {
  alert: Alert
  selected: boolean
  onSelect: () => void
  onVisibilityChange: () => void
  visibilityBusy: boolean
  canChangeVisibility: boolean
}) {
  return (
    <tr className={selected ? 'is-selected' : ''}>
      <td>
        <div className="message-cell">
          <Platform platform={a.platform} />
          <div className="message-cell-text">
            <div className="message-source">
              <button
                className="preview-select"
                aria-label={`Предпросмотр сообщения ${a.id}: ${a.chat_name}`}
                aria-pressed={selected}
                onClick={onSelect}
              >
                {a.chat_name}
              </button>
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
        {canChangeVisibility && (a.status === 'PROCESSED' || a.status === 'OFF_TOPIC') && (
          <button className="text-button" onClick={onVisibilityChange} disabled={visibilityBusy}>
            {a.status === 'OFF_TOPIC' ? 'Восстановить' : 'Не по теме'}
          </button>
        )}
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
