import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Edge } from '@xyflow/react'
import { RelationshipGraph } from '../components/RelationshipGraph'
import type { CardNode } from '../components/RelationshipGraph'
import { Empty, ErrorBox, Platform, RiskBadge } from '../components/ui'
import { EvidencePreview } from '../components/EvidencePreview'
import { sourceSummaries } from '../lib/analytics'
import type { Monitor } from '../lib/useMonitor'
import { statusLabels } from '../lib/model'

const PAGE_SIZE = 3
const MESSAGE_PITCH = 148

export function Graph({ monitor: m }: { monitor: Monitor }) {
  const [source, setSource] = useState('')
  const [selected, setSelected] = useState('')
  const [page, setPage] = useState(0)
  const sources = useMemo(() => sourceSummaries(m.alerts), [m.alerts])
  const active = sources.find((group) => group.key === source)
  const messages = active?.messages || m.alerts
  const focused = messages.find((alert) => alert.id === selected)
  const maxPage = Math.max(0, Math.ceil(messages.length / PAGE_SIZE) - 1)
  const currentPage = Math.min(page, maxPage)
  const visible = messages.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)
  const nodes: CardNode[] = active
    ? [
        {
          id: 'root',
          focusable: false,
          ariaRole: 'group',
          type: 'source',
          position: { x: 0, y: ((visible.length - 1) * MESSAGE_PITCH) / 2 + 22 },
          data: {
            kind: 'source',
            title: active.name,
            text: 'Сообщения из этого источника',
            count: active.count,
            platform: active.platform,
          },
        },
        ...visible.map((alert, index) => ({
          id: `message:${alert.id}`,
          type: 'message',
          position: { x: 345, y: index * MESSAGE_PITCH },
          selected: alert.id === selected,
          ariaLabel: `Сообщение ${alert.id}: ${alert.text}`,
          data: {
            kind: 'message' as const,
            title: alert.status === 'PROCESSED' ? 'Сообщение с оценкой' : statusLabels[alert.status],
            text: alert.text,
            platform: alert.platform,
            level: alert.risk_level,
            score: alert.risk_score,
          },
        })),
      ]
    : [
        {
          id: 'root',
          focusable: false,
          ariaRole: 'group',
          type: 'collection',
          position: { x: 0, y: (sources.length - 1) * 50 },
          data: {
            kind: 'collection',
            title: 'Мониторинг Blue',
            text: 'Сообщения из разрешённых источников',
            count: m.alerts.length,
          },
        },
        ...sources.map((group, index) => ({
          id: `source:${group.key}`,
          type: 'source',
          position: { x: 345, y: index * 100 },
          ariaLabel: `Источник ${group.name}`,
          data: {
            kind: 'source' as const,
            title: group.name,
            text: `${group.stats.by_level.HIGH} высокого риска · открыть сообщения`,
            count: group.count,
            platform: group.platform,
          },
        })),
      ]
  const edges: Edge[] = nodes
    .filter((node) => node.id !== 'root')
    .map((node) => ({ id: `root-${node.id}`, source: 'root', target: node.id, type: 'connection' }))
  function openSource(id: string) {
    setSource(id)
    setSelected('')
    setPage(0)
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Граф связей</h1>
          <p>От источника к сообщению, от сообщения — к доказательствам.</p>
        </div>
        <span className="graph-count">
          {sources.length} источников · {m.alerts.length} сообщений
        </span>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="relationship-toolbar">
        <label>
          Источник графа
          <select value={source} onChange={(event) => openSource(event.target.value)}>
            <option value="">Все источники</option>
            {sources.map((group) => (
              <option key={group.key} value={group.key}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        <div className="relationship-breadcrumb">
          <button onClick={() => openSource('')}>Источники</button>
          {active && (
            <>
              <ArrowRight size={14} />
              <span>{active.name}</span>
            </>
          )}
        </div>
      </div>
      <div className="relationship-workspace">
        <section className="relationship-canvas" aria-label="Связи источников и сообщений">
          <div className="relationship-canvas-heading">
            <div>
              <h2>{active ? 'Сообщения источника' : 'Карта источников'}</h2>
              <p>
                {active
                  ? 'Выберите сообщение, чтобы увидеть контекст.'
                  : 'Выберите источник на схеме или в списке.'}
              </p>
            </div>
            {active && (
              <button className="text-button" onClick={() => openSource('')}>
                <ArrowLeft size={14} />К источникам
              </button>
            )}
          </div>
          {m.alerts.length > 0 ? (
            <RelationshipGraph
              key={`${active?.key || 'all'}:${currentPage}`}
              nodes={nodes}
              edges={edges}
              onSelect={(node) => {
                if (node.id.startsWith('source:')) openSource(node.id.slice(7))
                if (node.id.startsWith('message:')) setSelected(node.id.slice(8))
              }}
            />
          ) : (
            <Empty
              title={m.loading ? 'Загружаем сообщения…' : 'Нет данных для схемы'}
              text="Схема появится после загрузки сообщений."
            />
          )}
          {active && (
            <div className="relationship-pagination">
              <span>
                {currentPage * PAGE_SIZE + 1}–
                {Math.min((currentPage + 1) * PAGE_SIZE, messages.length)} из {messages.length}{' '}
                сообщений
              </span>
              <button
                className="icon-button"
                aria-label="Предыдущие сообщения"
                disabled={currentPage === 0}
                onClick={() => {
                  setPage(currentPage - 1)
                  setSelected('')
                }}
              >
                <ChevronLeft size={17} />
              </button>
              <button
                className="icon-button"
                aria-label="Следующие сообщения"
                disabled={currentPage >= maxPage}
                onClick={() => {
                  setPage(currentPage + 1)
                  setSelected('')
                }}
              >
                <ChevronRight size={17} />
              </button>
            </div>
          )}
          <p className="relationship-caption">
            Связь означает принадлежность к источнику, а не участие в схеме.
          </p>
        </section>
        <aside className="relationship-details">
          {focused ? (
            <EvidencePreview alert={focused} demo={m.settings.mode === 'demo'} settings={m.settings} />
          ) : (
            <div className="relationship-list">
              <div>
                <h2>{active ? 'Сообщения' : 'Источники'}</h2>
                <p>
                  {active
                    ? 'Откройте сообщение для ручной проверки.'
                    : 'Источники из текущей выборки.'}
                </p>
              </div>
              {active ? (
                <div className="graph-message-list">
                  {messages.map((alert) => (
                    <Link key={alert.id} to={`/alerts/${encodeURIComponent(alert.id)}`}>
                      <div>
                        <strong>{alert.chat_name}</strong>
                        <span>{alert.text}</span>
                      </div>
                      <RiskBadge level={alert.risk_level} score={alert.risk_score} />
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="relationship-source-list">
                  {sources.map((group) => (
                    <button key={group.key} onClick={() => openSource(group.key)}>
                      <Platform platform={group.platform} />
                      <span>
                        <strong>{group.name}</strong>
                        <span>
                          {group.count} сообщений · {group.stats.by_level.HIGH} высокого риска
                        </span>
                      </span>
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
      <p className="page-note">
        {m.settings.mode === 'demo' ? 'Синтетическая выборка. ' : ''}На схеме показаны только
        источники и принадлежащие им сообщения.
      </p>
    </>
  )
}
