import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { ArrowUpRight, Clock3 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ActivityChart } from '../components/charts'
import { Empty, ErrorBox, Platform } from '../components/ui'
import { calculateStats, levelLabels, levels, reasonLabels } from '../lib/model'
import { isPublicDemoSession } from '../lib/auth'
import { reasonSummaries, selectAnalytics, sourceSummaries } from '../lib/analytics'
import type { Period, PlatformFilter } from '../lib/analytics'
import type { Monitor } from '../lib/useMonitor'

export function Analytics({ monitor: m }: { monitor: Monitor }) {
  const [period, setPeriod] = useState<Period>(isPublicDemoSession() ? 'all' : '24')
  const [platform, setPlatform] = useState<PlatformFilter>('all')
  const reduce = useReducedMotion()
  const now = m.lastUpdate ? Date.parse(m.lastUpdate) : Date.now()
  const alerts = selectAnalytics(m.alerts, period, platform, now)
  const stats = calculateStats(alerts)
  const processed = levels.reduce((sum, level) => sum + stats.by_level[level], 0)
  const sources = sourceSummaries(alerts)
  const reasons = reasonSummaries(alerts)
  const awaiting = stats.pending + stats.processing + stats.errors
  const query = `period=${period}${platform === 'all' ? '' : `&platform=${platform}`}`
  const entrance = (delay = 0) => ({
    initial: reduce ? (false as const) : { opacity: 0.5, transform: 'translateY(8px)' },
    animate: { opacity: 1, transform: 'translateY(0px)' },
    transition: { duration: 0.25, delay, ease: [0.23, 1, 0.32, 1] as const },
  })
  return (
    <>
      <div className="page-heading analytics-heading">
        <div>
          <h1>Аналитика</h1>
          <p>Сигналы риска, активность и источники — в одной выборке.</p>
        </div>
        <div className="period-selector" aria-label="Период аналитики">
          {(
            [
              ['24', '24 часа'],
              ['168', '7 дней'],
              ['all', 'Вся выборка'],
            ] as const
          ).map(([value, label]) => (
            <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="analytics-toolbar">
        <div className="platform-selector" aria-label="Платформа аналитики">
          {(['all', 'telegram', 'whatsapp'] as const).map((value) => (
            <button
              key={value}
              aria-pressed={platform === value}
              onClick={() => setPlatform(value)}
            >
              {value === 'all' ? 'Все платформы' : <Platform platform={value} label />}
            </button>
          ))}
        </div>
        <span>
          <Clock3 size={13} />
          Время Казахстана · UTC+5
        </span>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <motion.section className="analytics-overview" aria-label="Сводка аналитики" {...entrance()}>
        <div>
          <span>Сообщений в выборке</span>
          <strong>{alerts.length}</strong>
          <span>{sources.length} источников · {stats.off_topic} нерелевантных скрыто из основной очереди</span>
        </div>
        {levels.map((level) => (
          <Link className={level.toLowerCase()} key={level} to={`/?${query}&level=${level}`}>
            <span>
              <i className={`risk-tick ${level.toLowerCase()}`} />
              {levelLabels[level]} риск
            </span>
            <strong>{stats.by_level[level]}</strong>
            <span>
              Посмотреть сообщения <ArrowUpRight size={12} />
            </span>
          </Link>
        ))}
        <div>
          <span>Без оценки</span>
          <strong>{awaiting}</strong>
          <span>
            {stats.errors ? `${stats.errors} с ошибкой обработки` : 'Очередь и обработка'}
          </span>
        </div>
      </motion.section>
      <div className="analytics-primary-grid">
        <motion.section className="analytics-panel volume-panel" {...entrance(0.04)}>
          <div className="analytics-panel-heading">
            <div>
              <h2>Поток сообщений</h2>
              <p>
                {period === '24'
                  ? 'Последние 24 часа'
                  : period === '168'
                    ? 'Последние 7 дней'
                    : 'Все доступные сообщения'}{' '}
                · {alerts.length} в выборке
              </p>
            </div>
            <div className="volume-legend">
              <span>
                <i className="chart-key all" />
                Все
              </span>
              <span>
                <i className="chart-key high" />
                Высокий риск
              </span>
            </div>
          </div>
          <ActivityChart alerts={alerts} period={period} now={now} />
        </motion.section>
        <motion.section className="analytics-panel distribution-panel" {...entrance(0.08)}>
          <div className="analytics-panel-heading">
            <div>
              <h2>Риск в выборке</h2>
              <p>{processed} сообщений с готовой оценкой</p>
            </div>
          </div>
          <div className="distribution-track" aria-hidden="true">
            {levels.map((level) => (
              <span
                key={level}
                className={level.toLowerCase()}
                style={{ flex: stats.by_level[level] }}
              />
            ))}
          </div>
          <div className="distribution-rows">
            {levels.map((level) => (
              <Link key={level} to={`/?${query}&level=${level}`}>
                <span>
                  <i className={`risk-tick ${level.toLowerCase()}`} />
                  {levelLabels[level]}
                </span>
                <strong>{stats.by_level[level]}</strong>
                <span>
                  {processed ? Math.round((stats.by_level[level] / processed) * 100) : 0}%
                </span>
                <ArrowUpRight size={14} />
              </Link>
            ))}
          </div>
          <div className="processing-summary">
            <h3>Состояние обработки</h3>
            <div>
              <span>В очереди</span>
              <b>{stats.pending}</b>
            </div>
            <div>
              <span>Анализируются</span>
              <b>{stats.processing}</b>
            </div>
            <div>
              <span>Ошибки обработки</span>
              <b>{stats.errors}</b>
            </div>
          </div>
        </motion.section>
      </div>
      <div className="analytics-secondary-grid">
        <motion.section className="analytics-panel" {...entrance(0.12)}>
          <div className="analytics-panel-heading">
            <div>
              <h2>Источники, требующие внимания</h2>
              <p>Сначала — источники с большим числом сигналов высокого риска.</p>
            </div>
            <Link className="text-button" to="/chats">
              Все источники <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="source-analytics-list">
            {sources.map((source) => (
              <Link
                key={source.key}
                to={`/?period=${period}&platform=${source.platform}&chat=${encodeURIComponent(source.id)}`}
              >
                <Platform platform={source.platform} />
                <div className="source-analysis-main">
                  <strong>{source.name}</strong>
                  <div className="source-risk-track" aria-hidden="true">
                    {levels.map((level) => (
                      <span
                        className={level.toLowerCase()}
                        key={level}
                        style={{ flex: source.stats.by_level[level] }}
                      />
                    ))}
                    <span
                      className="unscored"
                      style={{
                        flex: source.stats.pending + source.stats.processing + source.stats.errors,
                      }}
                    />
                  </div>
                  <span>
                    {source.stats.by_level.HIGH} высокого риска · {source.count} сообщений
                  </span>
                </div>
                <ArrowUpRight size={16} />
              </Link>
            ))}
          </div>
          {!sources.length && (
            <Empty title="В выборке нет сообщений" text="Выберите другой период или платформу." />
          )}
          <div className="risk-bar-legend">
            {levels.map((level) => (
              <span key={level}>
                <i className={`risk-tick ${level.toLowerCase()}`} />
                {levelLabels[level]}
              </span>
            ))}
            <span>
              <i className="risk-tick unscored" />
              Без оценки
            </span>
          </div>
        </motion.section>
        <motion.section className="analytics-panel reasons-panel" {...entrance(0.16)}>
          <div className="analytics-panel-heading">
            <div>
              <h2>Почему сообщения отмечены</h2>
              <p>Число сообщений с каждым признаком.</p>
            </div>
          </div>
          <div className="reason-frequency-list">
            {reasons.slice(0, 6).map(([code, count]) => (
              <div key={code}>
                <div>
                  <span>{reasonLabels[code] || code}</span>
                  <strong>{count}</strong>
                </div>
                <div className="reason-track">
                  <span style={{ transform: `scaleX(${processed ? count / processed : 0})` }} />
                </div>
              </div>
            ))}
          </div>
          {!reasons.length && (
            <p className="analysis-empty">В этой выборке признаки не выделены.</p>
          )}
          <p className="reason-footnote">В одном сообщении может быть несколько признаков.</p>
        </motion.section>
      </div>
      <p className="metrics-note page-note">
        Счётчики описывают выбранные сообщения и не заменяют такую проверку, как измерение precision
        и recall на размеченных данных.
        {m.settings.mode === 'demo' ? ' Демонстрационные оценки заданы вручную.' : ''}
      </p>
    </>
  )
}
