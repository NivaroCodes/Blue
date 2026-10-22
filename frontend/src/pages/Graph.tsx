import { lazy, Suspense, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Minus, Plus, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ErrorBox, RiskBadge } from '../components/ui'
import type { Monitor } from '../lib/useMonitor'
import type { SceneNode } from '../components/Scene3D'
const Scene3D = lazy(() =>
  import('../components/Scene3D').then((module) => ({ default: module.Scene3D })),
)

export function Graph({ monitor: m }: { monitor: Monitor }) {
  const [source, setSource] = useState('')
  const [selected, setSelected] = useState('')
  const [command, setCommand] = useState('')
  const sources = [...new Map(m.alerts.map((alert) => [alert.chat_id, alert.chat_name])).entries()]
  const filtered = useMemo(
    () => m.alerts.filter((alert) => !source || source === alert.chat_id),
    [m.alerts, source],
  )
  // Polling returns new objects even when graph content is identical. Keep the
  // scene input stable so the analyst's camera and controls survive refreshes.
  const nodeSnapshot = JSON.stringify(
    filtered.map((alert) => ({ id: alert.id, source: alert.chat_id, score: alert.risk_score })),
  )
  const nodes = useMemo<SceneNode[]>(() => JSON.parse(nodeSnapshot), [nodeSnapshot])
  const focused = filtered.find((alert) => alert.id === selected)
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Граф связей</h1>
          <p>Увидеть источник. Найти сообщение. Проверить контекст.</p>
        </div>
        <span className="graph-count">
          {sources.length} источников · {m.alerts.length} сообщений
        </span>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="graph-workspace">
        <section className="graph-stage" aria-label="Пространственная карта источников">
          <div className="graph-top">
            <label>
              Источник графа
              <select
                value={source}
                onChange={(event) => {
                  setSource(event.target.value)
                  setSelected('')
                }}
              >
                <option value="">Все источники</option>
                {sources.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <span>Источник → сообщение</span>
          </div>
          <Suspense fallback={<p className="loading-state">Загружаем визуализацию…</p>}>
            <Scene3D nodes={nodes} command={command} onSelect={setSelected} />
          </Suspense>
          <div className="graph-controls" aria-label="Управление графом">
            {[
              { id: 'left', name: 'Повернуть влево', Icon: ArrowLeft },
              { id: 'right', name: 'Повернуть вправо', Icon: ArrowRight },
              { id: 'in', name: 'Приблизить', Icon: Plus },
              { id: 'out', name: 'Отдалить', Icon: Minus },
              { id: 'reset', name: 'Сбросить вид', Icon: RotateCcw },
            ].map(({ id, name, Icon }) => (
              <button
                key={id}
                className="icon-button"
                aria-label={name}
                onClick={() => setCommand(`${id}-${performance.now()}`)}
              >
                <Icon size={17} />
              </button>
            ))}
          </div>
          <div className="graph-legend">
            <span>
              <i className="source-node" />
              Источник
            </span>
            <span>
              <i className="risk-tick high" />
              Высокий
            </span>
            <span>
              <i className="risk-tick medium" />
              Средний
            </span>
            <span>
              <i className="risk-tick low" />
              Низкий
            </span>
            <span>
              <i className="risk-tick pending" />
              Нет оценки
            </span>
          </div>
        </section>
        <aside className="graph-results">
          <h2>{focused ? focused.chat_name : 'Сообщения в графе'}</h2>
          <p>
            {focused ? focused.text : 'Выберите точку на карте или откройте сообщение из списка.'}
          </p>
          <div className="graph-message-list">
            {(focused ? [focused] : filtered).map((alert) => (
              <Link key={alert.id} to={`/alerts/${encodeURIComponent(alert.id)}`}>
                <div>
                  <strong>{alert.chat_name}</strong>
                  <span>{alert.text}</span>
                </div>
                <RiskBadge level={alert.risk_level} score={alert.risk_score} />
              </Link>
            ))}
          </div>
          {focused && (
            <button className="text-button" onClick={() => setSelected('')}>
              Показать все сообщения
            </button>
          )}
          {!filtered.length && <p>В текущей выборке нет сообщений.</p>}
        </aside>
      </div>
      <p className="page-note">Связь означает принадлежность к источнику, а не участие в схеме.</p>
      <p className="page-note">
        {m.settings.mode === 'demo' ? 'Демонстрационный граф по синтетическим данным. ' : ''}
        Перетаскивайте карту для поворота. Кнопки управления и список сообщений доступны с
        клавиатуры.
      </p>
    </>
  )
}
