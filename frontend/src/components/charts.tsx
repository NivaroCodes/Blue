import { useId } from 'react'
import { levelLabels, levels } from '../lib/model'
import type { Alert, Stats } from '../lib/model'

export function ActivityChart({ alerts, large = false }: { alerts: Alert[]; large?: boolean }) {
  const id = useId().replace(/:/g, '')
  const end = Date.now()
  const bins = Array.from({ length: 12 }, (_, i) => {
    const start = end - (12 - i) * 2 * 3_600_000
    const items = alerts.filter((a) => {
      const t = +new Date(a.timestamp)
      return t >= start && t < start + 2 * 3_600_000
    })
    return {
      total: items.length,
      risk: items.filter((a) => a.risk_level === 'HIGH').length,
      label: new Intl.DateTimeFormat('ru-RU', {
        timeZone: 'Asia/Qyzylorda',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(start)),
    }
  })
  const max = Math.max(...bins.map((b) => b.total), 4)
  const points = bins.map((b, i) => `${45 + i * 58},${144 - (b.total / max) * 115}`).join(' ')
  const high = bins.map((b, i) => `${45 + i * 58},${144 - (b.risk / max) * 115}`).join(' ')
  return (
    <div className={`activity-chart ${large ? 'chart-large' : ''}`}>
      <svg
        viewBox="0 0 720 188"
        role="img"
        aria-label={`Активность за 24 часа: ${bins.reduce((n, b) => n + b.total, 0)} сообщений. Числа по интервалам доступны в таблице.`}
      >
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="var(--accent)" stopOpacity=".17" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity=".005" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <line
              x1="40"
              x2="696"
              y1={29 + i * 38.33}
              y2={29 + i * 38.33}
              stroke="var(--border)"
              strokeDasharray="3 5"
            />
            <text x="22" y={33 + i * 38.33} textAnchor="end">
              {Math.round(max * (1 - i / 3))}
            </text>
          </g>
        ))}
        <polygon points={`45,144 ${points} 683,144`} fill={`url(#${id})`} />
        <polyline
          points={points}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.6"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <polyline
          points={high}
          fill="none"
          stroke="var(--high)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          strokeDasharray="4 4"
        />
        {bins.map((b, i) => (
          <g key={i}>
            <circle
              cx={45 + i * 58}
              cy={144 - (b.total / max) * 115}
              r="3.5"
              fill="var(--surface)"
              stroke="var(--accent)"
              strokeWidth="2"
            >
              <title>
                {b.label}: {b.total} сообщений, высокий риск: {b.risk}
              </title>
            </circle>
            {i % 2 === 0 && (
              <text x={45 + i * 58} y="176" textAnchor="middle">
                {b.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <details className="chart-data">
        <summary>Данные графика</summary>
        <table>
          <caption>Двухчасовые интервалы, время Казахстана (UTC+5)</caption>
          <thead>
            <tr>
              <th>Время</th>
              <th>Всего</th>
              <th>Высокий риск</th>
            </tr>
          </thead>
          <tbody>
            {bins.map((b, i) => (
              <tr key={i}>
                <td>{b.label}</td>
                <td>{b.total}</td>
                <td>{b.risk}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}
export function RiskDonut({ stats }: { stats: Stats }) {
  const total = levels.reduce((n, l) => n + stats.by_level[l], 0)
  const high = total ? (stats.by_level.HIGH / total) * 100 : 0
  const medium = total ? (stats.by_level.MEDIUM / total) * 100 : 0
  return (
    <div className="risk-distribution">
      <div
        className="donut"
        role="img"
        aria-label={`Обработано: ${total}. ${levels.map((l) => `${levelLabels[l]}: ${stats.by_level[l]}`).join(', ')}`}
        style={{
          background: total
            ? `conic-gradient(var(--high) 0 ${high}%, var(--medium) ${high}% ${high + medium}%, var(--low) ${high + medium}% 100%)`
            : 'var(--surface-raised)',
        }}
      >
        <div>
          <strong>{total}</strong>
          <span>обработано</span>
        </div>
      </div>
      <div className="donut-legend">
        {levels.map((l) => (
          <div key={l}>
            <span className={`legend-dot ${l.toLowerCase()}`} />
            <span>{levelLabels[l]}</span>
            <b>{stats.by_level[l]}</b>
            <small>{total ? Math.round((stats.by_level[l] / total) * 100) : 0}%</small>
          </div>
        ))}
      </div>
    </div>
  )
}
