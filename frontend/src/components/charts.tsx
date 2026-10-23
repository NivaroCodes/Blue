import { useReducedMotion } from 'motion/react'
import {
  Area,
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { activityBins } from '../lib/analytics'
import type { Period } from '../lib/analytics'
import type { Alert } from '../lib/model'

export function ActivityChart({
  alerts,
  period,
  now,
}: {
  alerts: Alert[]
  period: Period
  now: number
}) {
  const reduce = useReducedMotion()
  const data = activityBins(alerts, period, now)
  const maximum = Math.max(1, ...data.map((bin) => bin.total))
  return (
    <div className="activity-chart-v2">
      <div className="activity-plot" data-testid="activity-chart">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart
            data={data}
            margin={{ top: 20, right: 14, bottom: 0, left: -22 }}
            accessibilityLayer
            title="Количество сообщений по времени"
          >
            <defs>
              <linearGradient id="blue-volume" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2455ed" stopOpacity={0.16} />
                <stop offset="100%" stopColor="#2455ed" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="#e9edf5" strokeDasharray="3 5" />
            <XAxis
              dataKey="label"
              axisLine={false}
              tickLine={false}
              minTickGap={38}
              tick={{ fill: '#657089', fontSize: 11 }}
              dy={10}
              height={42}
            />
            <YAxis
              allowDecimals={false}
              domain={[0, maximum]}
              axisLine={false}
              tickLine={false}
              width={48}
              tick={{ fill: '#657089', fontSize: 11 }}
            />
            <Tooltip
              cursor={{ stroke: '#b3c4f5', strokeDasharray: '3 3' }}
              content={({ active, payload }) => {
                const bin = payload?.[0]?.payload as (typeof data)[number] | undefined
                return active && bin ? (
                  <div className="activity-tooltip">
                    <strong>{bin.interval}</strong>
                    <div>
                      <i className="chart-key all" />
                      Всего сообщений <b>{bin.total}</b>
                    </div>
                    <div>
                      <i className="chart-key high" />
                      Высокий риск <b>{bin.high}</b>
                    </div>
                  </div>
                ) : null
              }}
            />
            <Area
              type="linear"
              dataKey="total"
              name="Все сообщения"
              stroke="#2455ed"
              fill="url(#blue-volume)"
              strokeWidth={2.5}
              isAnimationActive={!reduce}
              animationDuration={280}
              animationEasing="ease-out"
              dot={false}
              activeDot={{ r: 5, stroke: 'white', strokeWidth: 3 }}
            />
            <Line
              type="linear"
              dataKey="high"
              name="Высокий риск"
              stroke="#b42338"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={!reduce}
              animationDuration={280}
              animationEasing="ease-out"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <details className="activity-data">
        <summary>Данные графика</summary>
        <div className="table-scroll">
          <table>
            <caption>Интервалы по времени Казахстана · UTC+5</caption>
            <thead>
              <tr>
                <th>Интервал</th>
                <th>Сообщений</th>
                <th>Высокий риск</th>
              </tr>
            </thead>
            <tbody>
              {data.map((bin) => (
                <tr key={bin.key}>
                  <td>{bin.interval}</td>
                  <td>{bin.total}</td>
                  <td>{bin.high}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
