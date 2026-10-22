import { KrakenMark } from '../components/KrakenMark'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Filter,
  Inbox,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { ActivityChart, RiskDonut } from '../components/charts'
import {
  Empty,
  ErrorBox,
  Panel,
  Platform,
  ProcessingBadge,
  Reasons,
  ReviewBadge,
  RiskBadge,
} from '../components/ui'
import { dateTime, levelLabels, levels, time } from '../lib/model'
import type { Alert, Level } from '../lib/model'
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
  const newHigh = m.alerts.filter(
    (a) => a.risk_level === 'HIGH' && a.review_status === 'NEW',
  ).length
  return (
    <>
      <section className="kraken-banner" aria-label="Kraken — видеть глубже">
        <div className="banner-copy">
          <span className="banner-kicker">KRAKEN / SIGNAL INTELLIGENCE</span>
          <h2>
            Видеть <em>глубже.</em>
          </h2>
          <p>Находите скрытые риски. Принимайте осознанные решения.</p>
        </div>
        <div className="banner-art" aria-hidden="true">
          <span className="banner-orbit" />
          <KrakenMark />
          <span className="banner-coordinate">SAFENET KZ / 2026</span>
        </div>
        <span className="banner-index">01 — ОБНАРУЖЕНИЕ</span>
      </section>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span className="tiny-accent-line" /> ОБЗОР БЕЗОПАСНОСТИ
          </div>
          <h1>
            Мониторинг рисков<span className="heading-dot">.</span>
          </h1>
          <p>Сигналы, которые заслуживают вашего внимания.</p>
        </div>
        <div className="heading-actions">
          {m.settings.mode === 'demo' && (
            <button className="button" onClick={onDemoMessage}>
              <Plus size={16} /> Демо-сообщение
            </button>
          )}
          <button
            className="button button-primary"
            onClick={exportData}
            disabled={m.loading || !filtered.length}
          >
            <ArrowDownToLine size={16} /> Экспорт
          </button>
        </div>
      </div>
      <div className="context-strip">
        <div>
          <span className={`live-dot ${m.error ? 'is-error' : ''}`} />
          <b>
            {m.error
              ? 'Связь прервана'
              : m.settings.polling
                ? 'Live-мониторинг'
                : 'Обновление на паузе'}
          </b>
          <span className="strip-divider" />
          <span>{m.settings.mode === 'demo' ? 'Синтетические данные' : 'Подключение к API'}</span>
          <span className="context-update">
            {m.lastUpdate ? `Обновлено в ${time(m.lastUpdate)} · UTC+5` : 'Ожидание данных'}
          </span>
        </div>
        <button
          className="text-button"
          onClick={() => {
            try {
              m.updateSettings({ ...m.settings, polling: !m.settings.polling })
              setSettingsError('')
            } catch (e) {
              setSettingsError(e instanceof Error ? e.message : 'Не удалось сохранить настройку.')
            }
          }}
          aria-label={
            m.settings.polling ? 'Приостановить live-обновления' : 'Включить live-обновления'
          }
        >
          {m.settings.polling ? <Pause size={13} /> : <Play size={13} />}
          {m.settings.polling ? 'Пауза' : 'Продолжить'}
        </button>
      </div>
      {settingsError && (
        <p className="form-error" role="alert">
          {settingsError}
        </p>
      )}
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="stat-grid">
        <StatCard
          label="Всего сообщений"
          value={m.stats.total_messages}
          icon="total"
          sub="В подключённой выборке"
          active={!level}
          onClick={() => filter('level', '')}
          loading={m.loading}
        />
        {levels.map((l) => (
          <StatCard
            key={l}
            label={`${levelLabels[l]} риск`}
            value={m.stats.by_level[l]}
            icon={l}
            sub={
              l === 'HIGH'
                ? 'Приоритетная проверка'
                : l === 'MEDIUM'
                  ? 'Нужно больше контекста'
                  : 'Без выраженных признаков'
            }
            active={level === l}
            onClick={() => filter('level', level === l ? '' : l)}
            loading={m.loading}
          />
        ))}
      </div>
      <div className="chart-grid">
        <Panel
          title="Активность сообщений"
          description="Последние 24 часа · загруженная выборка"
          action={
            <div className="chart-legend">
              <span>
                <i className="legend-dot accent" />
                Все сообщения
              </span>
              <span>
                <i className="legend-dot high" />
                Высокий риск
              </span>
            </div>
          }
        >
          <ActivityChart alerts={m.alerts} />
        </Panel>
        <Panel title="Распределение рисков" description="Только обработанные сообщения">
          <RiskDonut stats={m.stats} />
        </Panel>
      </div>
      <div className="queue-insight">
        <span className="insight-icon">
          <ShieldCheck size={20} />
        </span>
        <div>
          <b>
            {newHigh
              ? `${newHigh} сообщений высокого риска ждут проверки`
              : 'Все сигналы высокого риска проверены'}
          </b>
          <span>Оценка — повод изучить контекст. Решение остаётся за вами.</span>
        </div>
        <button
          className="text-button"
          onClick={() => {
            applyParams({ level: 'HIGH', review: 'NEW', period: 'all' })
            setPage(1)
          }}
        >
          К проверке <ArrowRight size={16} />
        </button>
      </div>
      <Panel className="alerts-panel">
        <div className="alerts-heading">
          <div>
            <h2>
              Лента сообщений <span className="count-badge">{m.alerts.length}</span>
            </h2>
            <p>От сигнала к осмысленному решению.</p>
          </div>
          <div className="feed-tools">
            <select
              aria-label="Период ленты"
              value={period}
              onChange={(e) => filter('period', e.target.value)}
            >
              <option value="24">Последние 24 часа</option>
              <option value="168">Последние 7 дней</option>
              <option value="all">Всё время</option>
            </select>
            <button
              className="icon-button"
              aria-label="Обновить данные"
              onClick={m.refresh}
              disabled={m.loading}
            >
              <RefreshCw size={17} className={m.loading ? 'spin' : ''} />
            </button>
          </div>
        </div>
        <div className="feed-tabs">
          <button className={!review ? 'selected' : ''} onClick={() => filter('review', '')}>
            Все сообщения <span>{m.alerts.length}</span>
          </button>
          <button
            className={review === 'NEW' ? 'selected' : ''}
            onClick={() => filter('review', 'NEW')}
          >
            На проверке <span>{m.alerts.filter((a) => a.review_status === 'NEW').length}</span>
          </button>
          <button
            className={review === 'REVIEWED' ? 'selected' : ''}
            onClick={() => filter('review', 'REVIEWED')}
          >
            <CheckCheck size={14} /> Проверенные
          </button>
          <button
            className={review === 'FALSE_POSITIVE' ? 'selected' : ''}
            onClick={() => filter('review', 'FALSE_POSITIVE')}
          >
            Ложные срабатывания
          </button>
        </div>
        <div className="filters">
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="Поиск сообщений"
              placeholder="Поиск по сообщению или чату…"
              value={search}
              onChange={(e) => filter('q', e.target.value)}
            />
            <kbd>⌕</kbd>
          </label>
          <div className="filter-select">
            <Filter size={14} />
            <select
              aria-label="Платформа"
              value={platform}
              onChange={(e) => filter('platform', e.target.value)}
            >
              <option value="">Все платформы</option>
              <option value="telegram">Telegram</option>
              <option value="whatsapp">WhatsApp</option>
            </select>
          </div>
          <select aria-label="Чат" value={chat} onChange={(e) => filter('chat', e.target.value)}>
            <option value="">Все чаты</option>
            {chats.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <div className="filter-select">
            <SlidersHorizontal size={14} />
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
          </div>
          {filterCount > 0 && (
            <button
              className="text-button reset-filters"
              onClick={() => {
                applyParams({ period })
                setPage(1)
              }}
            >
              Сбросить · {filterCount}
            </button>
          )}
        </div>
        {m.loading && !m.alerts.length ? (
          <div className="loading-state" role="status">
            <RefreshCw className="spin" size={21} /> Загружаем сообщения…
          </div>
        ) : !rows.length ? (
          <Empty
            title="Сообщений не найдено"
            text={
              m.error
                ? 'Проверьте подключение и повторите загрузку.'
                : 'Попробуйте другой запрос или измените фильтры.'
            }
            action={
              <button
                className="button"
                onClick={() => {
                  applyParams({ period: 'all' })
                  setPage(1)
                }}
              >
                Сбросить фильтры
              </button>
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="alerts-table">
              <thead>
                <tr>
                  <th>Сообщение / источник</th>
                  <th>
                    <button onClick={() => setSort(sort === 'risk' ? 'latest' : 'risk')}>
                      Уровень риска <ArrowDown size={12} />
                    </button>
                  </th>
                  <th>Статус проверки</th>
                  <th>Получено</th>
                  <th>
                    <span className="sr-only">Детали</span>
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
              ? `${(currentPage - 1) * 6 + 1}–${Math.min(currentPage * 6, filtered.length)} из ${filtered.length} сообщений`
              : '0 сообщений'}
            <span className="loaded-label"> · загруженная выборка</span>
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
      </Panel>
      <div className="pipeline-summary">
        <span>
          <span className="status-dot" /> Очередь обработки
        </span>
        <span>
          Ожидают <b>{m.stats.pending}</b>
        </span>
        <span>
          Анализируются <b>{m.stats.processing}</b>
        </span>
        <span>
          Ошибки <b className={m.stats.errors ? 'error-text' : ''}>{m.stats.errors}</b>
        </span>
        <Link to="/analytics">
          Подробнее <ArrowUpRight size={13} />
        </Link>
      </div>
    </>
  )
}
function StatCard({
  label,
  value,
  sub,
  icon,
  active,
  onClick,
  loading,
}: {
  label: string
  value: number
  sub: string
  icon: Level | 'total'
  active: boolean
  onClick: () => void
  loading: boolean
}) {
  const Icon =
    icon === 'total'
      ? Inbox
      : icon === 'HIGH'
        ? CircleAlert
        : icon === 'MEDIUM'
          ? CircleAlert
          : ShieldCheck
  return (
    <button
      className={`stat-card ${icon.toLowerCase()} ${active ? 'stat-active' : ''}`}
      onClick={onClick}
      aria-pressed={active}
    >
      <div className="stat-label">
        <span>{label}</span>
        <span className="stat-icon">
          <Icon size={17} />
        </span>
      </div>
      <strong>{loading ? '—' : value.toLocaleString('ru-RU')}</strong>
      <div className="stat-sub">
        <span className="status-dot" />
        {sub}
        <ArrowUpRight size={13} />
      </div>
    </button>
  )
}
function AlertRow({ alert: a }: { alert: Alert }) {
  return (
    <tr>
      <td>
        <div className="message-cell">
          <span className="source-avatar">
            <Platform platform={a.platform} />
          </span>
          <div className="message-cell-text">
            <div className="message-source">
              <b>{a.chat_name}</b>
              <span>{a.platform === 'telegram' ? 'Telegram' : 'WhatsApp'}</span>
            </div>
            <Link className="message-preview" to={`/alerts/${encodeURIComponent(a.id)}`}>
              {a.text}
            </Link>
            {a.status === 'PROCESSED' ? (
              <Reasons alert={a} />
            ) : (
              <ProcessingBadge status={a.status} />
            )}
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
          <ChevronRight size={18} />
        </Link>
      </td>
    </tr>
  )
}
