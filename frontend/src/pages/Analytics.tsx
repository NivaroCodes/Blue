import {
  Activity,
  ArrowUpRight,
  CheckCheck,
  CircleAlert,
  Clock3,
  Layers,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ActivityChart, RiskDonut } from '../components/charts'
import { ErrorBox, Panel, Platform } from '../components/ui'
import { reasonLabels } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'

export function Analytics({ monitor: m }: { monitor: Monitor }) {
  const processed = m.alerts.filter((a) => a.status === 'PROCESSED')
  const reviewed = processed.filter((a) => a.review_status !== 'NEW')
  const falsePositives = processed.filter((a) => a.review_status === 'FALSE_POSITIVE').length
  const reasons = Object.entries(
    m.alerts
      .flatMap((a) => [...new Set(a.reasons.map((r) => r.code))])
      .reduce<Record<string, number>>((acc, code) => {
        acc[code] = (acc[code] || 0) + 1
        return acc
      }, {}),
  ).sort((a, b) => b[1] - a[1])
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span className="tiny-accent-line" /> ПОНЯТНАЯ КАРТИНА
          </div>
          <h1>
            Аналитика сигналов<span className="heading-dot">.</span>
          </h1>
          <p>Что происходит в загруженной выборке и что уже проверено.</p>
        </div>
        <span className="date-chip">
          <Layers size={15} /> Вся загруженная выборка
        </span>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="analytics-summary">
        <Panel>
          <span className="analytics-icon">
            <Activity size={19} />
          </span>
          <p>Обработано сообщений</p>
          <strong>{processed.length}</strong>
          <span>из {m.alerts.length} загруженных</span>
        </Panel>
        <Panel>
          <span className="analytics-icon">
            <CheckCheck size={19} />
          </span>
          <p>Проверено аналитиком</p>
          <strong>{reviewed.length}</strong>
          <span>
            {processed.length ? Math.round((reviewed.length / processed.length) * 100) : 0}%
            обработанных сообщений
          </span>
        </Panel>
        <Panel>
          <span className="analytics-icon">
            <ShieldCheck size={19} />
          </span>
          <p>Отмечено как ложные</p>
          <strong>{falsePositives}</strong>
          <span>Решения аналитика, не метрика модели</span>
        </Panel>
      </div>
      <div className="chart-grid">
        <Panel title="Поток сообщений" description="Последние 24 часа · время Казахстана (UTC+5)">
          <ActivityChart alerts={m.alerts} large />
        </Panel>
        <Panel title="Распределение рисков" description="Агрегаты Backend API или демоданных">
          <RiskDonut stats={m.stats} />
        </Panel>
      </div>
      <div className="analytics-columns">
        <Panel
          title="Какие признаки встречаются чаще"
          description="Количество сообщений с каждым признаком"
        >
          <div className="reason-chart">
            {reasons.length ? (
              reasons.map(([code, count]) => (
                <div key={code}>
                  <div>
                    <span>{reasonLabels[code] || code}</span>
                    <b>{count}</b>
                  </div>
                  <div className="bar-track">
                    <span style={{ width: `${(count / (reasons[0]?.[1] || 1)) * 100}%` }} />
                  </div>
                </div>
              ))
            ) : (
              <p className="subtle">В загруженной выборке пока нет выделенных признаков.</p>
            )}
          </div>
        </Panel>
        <Panel title="Источники сообщений" description="Доля платформ в загруженной выборке">
          <div className="platform-stats">
            {(['telegram', 'whatsapp'] as const).map((platform) => {
              const count = m.alerts.filter((a) => a.platform === platform).length
              return (
                <div key={platform}>
                  <div>
                    <Platform platform={platform} label />
                    <strong>{count}</strong>
                  </div>
                  <div className="bar-track">
                    <span
                      style={{ width: `${m.alerts.length ? (count / m.alerts.length) * 100 : 0}%` }}
                    />
                  </div>
                  <p>
                    {m.alerts.length ? Math.round((count / m.alerts.length) * 100) : 0}% сообщений
                  </p>
                </div>
              )
            })}
          </div>
          <div className="pipeline-stats">
            <h3>
              <Clock3 size={15} /> Состояние обработки
            </h3>
            <div>
              <span>В очереди</span>
              <b>{m.stats.pending}</b>
            </div>
            <div>
              <span>Анализируются</span>
              <b>{m.stats.processing}</b>
            </div>
            <div>
              <span>Ошибки</span>
              <b className="error-text">{m.stats.errors}</b>
            </div>
          </div>
        </Panel>
      </div>
      <div className="metrics-note">
        <span>
          <CircleAlert size={22} />
        </span>
        <div>
          <h3>Точность измеряется на отдельном тестовом наборе</h3>
          <p>
            Precision, recall и false-positive rate появятся после оценки AI-модуля на размеченных
            данных. Счётчики и решения аналитика на этой странице не заменяют такую проверку.
            {m.settings.mode === 'demo' && ' Оценки риска в деморежиме заданы вручную.'}
          </p>
        </div>
        <Link to="/">
          К сообщениям <ArrowUpRight size={15} />
        </Link>
      </div>
    </>
  )
}
