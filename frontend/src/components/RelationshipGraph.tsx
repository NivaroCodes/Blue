import { useRef } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { ReactFlow, Handle, Position, getSmoothStepPath } from '@xyflow/react'
import type { Node, NodeProps, Edge, EdgeProps, ReactFlowInstance } from '@xyflow/react'
import { Platform, RiskBadge } from './ui'
import { BlueMark } from './BlueMark'
import type { Alert, Level } from '../lib/model'
import '@xyflow/react/dist/style.css'

export type GraphCardData = {
  kind: 'collection' | 'source' | 'message'
  title: string
  text: string
  count?: number
  platform?: Alert['platform']
  level?: Level | null
  score?: number | null
}
export type CardNode = Node<GraphCardData>

function GraphCard({ data }: NodeProps<CardNode>) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={`flow-card flow-${data.kind}`}
      initial={reduce ? false : { opacity: 0.5, transform: 'translateX(-8px)' }}
      animate={{ opacity: 1, transform: 'translateX(0px)' }}
      transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
    >
      {data.kind !== 'collection' && (
        <Handle type="target" position={Position.Left} isConnectable={false} />
      )}
      <div className="flow-card-title">
        {data.platform ? <Platform platform={data.platform} /> : <BlueMark />}
        <strong>{data.title}</strong>
        {data.count !== undefined && <b>{data.count}</b>}
      </div>
      <p>{data.text}</p>
      {data.kind === 'message' && <RiskBadge level={data.level ?? null} score={data.score} />}
      {data.kind !== 'message' && (
        <Handle type="source" position={Position.Right} isConnectable={false} />
      )}
    </motion.div>
  )
}

function Connection(edge: EdgeProps) {
  const reduce = useReducedMotion()
  const [path] = getSmoothStepPath({
    sourceX: edge.sourceX,
    sourceY: edge.sourceY,
    targetX: edge.targetX,
    targetY: edge.targetY,
    sourcePosition: edge.sourcePosition,
    targetPosition: edge.targetPosition,
    borderRadius: 18,
  })
  return (
    <motion.path
      className="react-flow__edge-path relationship-path"
      d={path}
      fill="none"
      stroke="#a8bdeb"
      strokeWidth={1.7}
      initial={reduce ? false : { pathLength: 0 }}
      animate={{ pathLength: 1 }}
      transition={{ duration: 0.28, ease: [0.23, 1, 0.32, 1] }}
    />
  )
}
const nodeTypes = { collection: GraphCard, source: GraphCard, message: GraphCard }
const edgeTypes = { connection: Connection }

export function RelationshipGraph({
  nodes,
  edges,
  onSelect,
}: {
  nodes: CardNode[]
  edges: Edge[]
  onSelect: (node: CardNode) => void
}) {
  const instance = useRef<ReactFlowInstance<CardNode, Edge> | null>(null)
  const reduce = useReducedMotion()
  return (
    <div
      className="relationship-diagram"
      role="group"
      aria-label="Интерактивная схема"
      onKeyDownCapture={(event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return
        const element = (event.target as HTMLElement).closest<HTMLElement>('.react-flow__node')
        const node = nodes.find((item) => item.id === element?.dataset.id)
        if (!node || node.id === 'root') return
        event.preventDefault()
        event.stopPropagation()
        onSelect(node)
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onInit={(flow) => {
          instance.current = flow
        }}
        onNodeClick={(_, node) => onSelect(node)}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.35}
        maxZoom={1.5}
        panOnScroll
        zoomOnScroll={false}
        preventScrolling={false}
        ariaLabelConfig={{
          'node.a11yDescription.default': 'Выберите источник или сообщение клавишей Enter.',
          'controls.zoomIn.ariaLabel': 'Приблизить',
          'controls.zoomOut.ariaLabel': 'Отдалить',
        }}
      ></ReactFlow>
      <div className="relationship-controls" aria-label="Управление схемой">
        <button
          className="icon-button"
          aria-label="Приблизить"
          onClick={() => instance.current?.zoomIn({ duration: reduce ? 0 : 180 })}
        >
          <Plus size={17} />
        </button>
        <button
          className="icon-button"
          aria-label="Отдалить"
          onClick={() => instance.current?.zoomOut({ duration: reduce ? 0 : 180 })}
        >
          <Minus size={17} />
        </button>
        <button
          className="icon-button"
          aria-label="Показать всю схему"
          onClick={() =>
            instance.current?.fitView({ padding: 0.15, maxZoom: 1, duration: reduce ? 0 : 180 })
          }
        >
          <Maximize2 size={17} />
        </button>
      </div>
    </div>
  )
}
