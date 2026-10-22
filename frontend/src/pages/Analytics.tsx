import { ActivityChart } from '../components/charts'
import { ErrorBox } from '../components/ui'
import { levelLabels, levels, reasonLabels } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'

export function Analytics({ monitor: m }: { monitor: Monitor }) {
  const processed = m.alerts.filter((a) => a.status === 'PROCESSED')
  const reviewed = processed.filter((a) => a.review_status !== 'NEW')
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
          <h1>Аналитика</h1>
          <p>По загруженной выборке · время UTC+5</p>
        </div>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <dl className="analytics-totals">
        <div>
          <dt>Сообщений</dt>
          <dd>{m.alerts.length}</dd>
        </div>
        <div>
          <dt>Обработано</dt>
          <dd>{processed.length}</dd>
        </div>
        <div>
          <dt>Проверено человеком</dt>
          <dd>{reviewed.length}</dd>
        </div>
      </dl>
      <section className="activity-section">
        <div className="section-heading">
          <h2>Активность за 24 часа</h2>
          <div className="chart-legend">
            <span>
              <i className="legend-line" />
              Все сообщения
            </span>
            <span>
              <i className="legend-line high" />
              Высокий риск
            </span>
          </div>
        </div>
        <ActivityChart alerts={m.alerts} large />
      </section>
      <div className="analysis-columns">
        <section>
          <h2>Распределение рисков</h2>
          <div className="analysis-list">
            {levels.map((l) => (
              <div key={l}>
                <span>
                  <i className={`risk-tick ${l.toLowerCase()}`} />
                  {levelLabels[l]}
                </span>
                <b>{m.stats.by_level[l]}</b>
              </div>
            ))}
          </div>
          <details className="plain-disclosure">
            <summary>Очередь обработки</summary>
            <dl>
              <div>
                <dt>В очереди</dt>
                <dd>{m.stats.pending}</dd>
              </div>
              <div>
                <dt>Анализируются</dt>
                <dd>{m.stats.processing}</dd>
              </div>
              <div>
                <dt>Ошибки</dt>
                <dd>{m.stats.errors}</dd>
              </div>
            </dl>
          </details>
        </section>
        <section>
          <h2>Частые признаки</h2>
          <div className="analysis-list">
            {reasons.slice(0, 5).map(([code, count]) => (
              <div key={code}>
                <span>{reasonLabels[code] || code}</span>
                <b>{count}</b>
              </div>
            ))}
          </div>
        </section>
      </div>
      <p className="metrics-note page-note">
        Счётчики описывают выборку и не заменяют такую проверку, как оценка precision и recall на
        отдельном размеченном наборе. В демо оценки заданы вручную.
      </p>
    </>
  )
}
