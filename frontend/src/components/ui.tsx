import { BlueMark } from './BlueMark'
import {
  AlertCircle,
  ArrowUpRight,
  CheckCheck,
  CircleDot,
  MessageCircle,
  Send,
  ShieldCheck,
} from 'lucide-react'
import { levelLabels, reasonLabels, reviewLabels, statusLabels } from '../lib/model'
import type { Alert, Level } from '../lib/model'
import type { ReactNode } from 'react'

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand ${small ? 'brand-small' : ''}`}>
      <BlueMark />
      {!small && <span className="brand-wordmark">blue</span>}
    </span>
  )
}
export function Platform({
  platform,
  label = false,
}: {
  platform: Alert['platform']
  label?: boolean
}) {
  const Icon = platform === 'telegram' ? Send : MessageCircle
  return (
    <span className={`platform platform-${platform}`}>
      <Icon size={14} aria-hidden="true" />
      {label && (platform === 'telegram' ? 'Telegram' : 'WhatsApp')}
    </span>
  )
}
export function RiskBadge({ level, score }: { level: Level | null; score?: number | null }) {
  return level ? (
    <span className={`risk-badge ${level.toLowerCase()}`}>
      <span className="status-dot" />
      {levelLabels[level]}
      {score !== undefined && score !== null && <b>{score}</b>}
    </span>
  ) : (
    <span className="risk-badge neutral">Нет оценки</span>
  )
}
export function ReviewBadge({ status }: { status: Alert['review_status'] }) {
  const Icon = status === 'NEW' ? CircleDot : status === 'REVIEWED' ? CheckCheck : ShieldCheck
  return (
    <span className={`review-badge review-${status.toLowerCase()}`}>
      <Icon size={13} aria-hidden="true" />
      {reviewLabels[status]}
    </span>
  )
}
export function ProcessingBadge({ status }: { status: Alert['status'] }) {
  return (
    <span className={`processing-badge ${status === 'ERROR' ? 'error-text' : ''}`}>
      <CircleDot size={12} aria-hidden="true" />
      {statusLabels[status]}
    </span>
  )
}
export function Panel({
  title,
  description,
  action,
  children,
  className = '',
}: {
  title?: string
  description?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-head">
          <div>
            <h2>{title}</h2>
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string
  text: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <ShieldCheck size={28} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  )
}
export function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={19} />
      <div>
        <b>Не удалось получить данные</b>
        <p>{message}</p>
      </div>
      {retry && (
        <button className="button button-small" onClick={retry}>
          Повторить
        </button>
      )}
    </div>
  )
}
export function Reasons({ alert }: { alert: Alert }) {
  return (
    <div className="reason-tags">
      {alert.reasons.slice(0, 2).map((r, i) => (
        <span key={`${r.code}-${i}`}>{reasonLabels[r.code] || r.code}</span>
      ))}
      {alert.reasons.length > 2 && <span>+{alert.reasons.length - 2}</span>}
    </div>
  )
}
export function EvidenceText({ text, evidence }: { text: string; evidence: string[] }) {
  const ranges: [number, number][] = []
  for (const snippet of evidence.filter(Boolean)) {
    let from = 0
    while (from < text.length) {
      const start = text.toLocaleLowerCase().indexOf(snippet.toLocaleLowerCase(), from)
      if (start < 0) break
      ranges.push([start, start + snippet.length])
      from = start + snippet.length
    }
  }
  ranges.sort((a, b) => a[0] - b[0])
  const merged: [number, number][] = []
  for (const range of ranges) {
    const last = merged.at(-1)
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1])
    else merged.push([...range])
  }
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const [start, end] of merged) {
    nodes.push(text.slice(cursor, start), <mark key={start}>{text.slice(start, end)}</mark>)
    cursor = end
  }
  nodes.push(text.slice(cursor))
  return <>{nodes}</>
}
export function SmallArrow() {
  return <ArrowUpRight size={16} aria-hidden="true" />
}
