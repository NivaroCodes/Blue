import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowLeft,
  CheckCheck,
  CheckCircle2,
  FileText,
  Fingerprint,
  Info,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getAlert, saveReview } from '../lib/api'
import { dateTime, reasonLabels, reviewLabels } from '../lib/model'
import type { Alert, Review } from '../lib/model'
import type { Monitor } from '../lib/useMonitor'
import {
  Empty,
  ErrorBox,
  EvidenceText,
  Panel,
  Platform,
  ProcessingBadge,
  ReviewBadge,
  RiskBadge,
} from '../components/ui'

export function AlertDetail({
  monitor: m,
  notify,
}: {
  monitor: Monitor
  notify: (s: string) => void
}) {
  const { id = '' } = useParams()
  const [alert, setAlert] = useState<Alert | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setAlert(null)
    setError('')
    setLoading(true)
    void getAlert(m.settings, id, AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]))
      .then((a) => {
        if (active) setAlert(a)
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : 'Не удалось загрузить детали.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [id, m.settings, attempt])
  useEffect(() => {
    const latest = m.alerts.find((a) => a.id === id)
    if (latest) setAlert(latest)
  }, [m.alerts, id])
  return (
    <>
      <Link className="back-link" to="/">
        <ArrowLeft size={16} /> Назад к мониторингу
      </Link>
      <div className="page-heading detail-heading">
        <div>
          <h1>Проверка сообщения</h1>
          <p>Изучите контекст и сохраните решение.</p>
        </div>
      </div>
      {loading && (
        <div className="loading-state" role="status">
          <RefreshCw className="spin" /> Загружаем детали…
        </div>
      )}
      {error && <ErrorBox message={error} retry={() => setAttempt((n) => n + 1)} />}
      {!loading && !error && !alert && (
        <Empty title="Сообщение не найдено" text="Возможно, оно было удалено из источника." />
      )}
      {alert && !loading && (
        <div className="detail-grid">
          <div className="detail-main">
            <Panel title="Исходное сообщение" action={<Platform platform={alert.platform} label />}>
              <div className="message-meta">
                <span className="chat-avatar">
                  <MessageSquare size={22} />
                </span>
                <div>
                  <h3>{alert.chat_name}</h3>
                  <p>{dateTime(alert.timestamp)} · UTC+5</p>
                </div>
                <ReviewBadge status={alert.review_status} />
              </div>
              <blockquote className="original-message">
                <EvidenceText text={alert.text} evidence={alert.reasons.map((r) => r.evidence)} />
              </blockquote>
              <div className="message-foot">
                <Fingerprint size={14} />
                <span>{alert.sender_hash}</span>
                <span>·</span>
                <span>{alert.message_id}</span>
              </div>
              {m.settings.mode === 'demo' && (
                <div className="inline-note">
                  <Info size={15} />
                  <span>Синтетический пример. Текст и оценка подготовлены для демонстрации.</span>
                </div>
              )}
            </Panel>
            <Panel
              title="Почему сообщение отмечено"
              description="Признаки и точные фрагменты, на которых основана оценка"
              action={<span className="count-badge">{alert.reasons.length}</span>}
            >
              <div className="evidence-list">
                {alert.reasons.length ? (
                  alert.reasons.map((reason, i) => (
                    <div className="evidence-item" key={`${reason.code}-${i}`}>
                      <span className="evidence-number">{String(i + 1).padStart(2, '0')}</span>
                      <div>
                        <h3>{reasonLabels[reason.code] || reason.code}</h3>
                        <blockquote>«{reason.evidence}»</blockquote>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="no-evidence">
                    <ShieldCheck size={23} />
                    <p>
                      {alert.status === 'PROCESSED'
                        ? 'Выраженных признаков в этом сообщении не выделено.'
                        : 'Фрагменты появятся после успешного анализа.'}
                    </p>
                  </div>
                )}
              </div>
            </Panel>
            {alert.explanation && (
              <details className="explanation-disclosure">
                <summary>Объяснение и данные модели</summary>
                <p className="explanation">{alert.explanation}</p>
                <div className="model-meta">
                  <span>
                    Версия: <b className="mono">{alert.model_version}</b>
                  </span>
                  {alert.confidence !== null && (
                    <span>
                      Уверенность {m.settings.mode === 'demo' ? '(демо)' : 'модели'}:{' '}
                      <b>{Math.round(alert.confidence * 100)}%</b>
                    </span>
                  )}
                </div>
              </details>
            )}
          </div>
          <aside className="detail-aside">
            <Panel title="Оценка риска">
              <div className={`score-display ${alert.risk_level?.toLowerCase() || ''}`}>
                <div className="score-number">
                  {alert.risk_score ?? '—'}
                  <span>/ 100</span>
                </div>
                <RiskBadge level={alert.risk_level} />
                {alert.status !== 'PROCESSED' && <ProcessingBadge status={alert.status} />}
                <p>
                  {alert.status === 'PROCESSED'
                    ? 'Требует оценки аналитика'
                    : 'Оценка ещё не получена'}
                </p>
              </div>
            </Panel>
            <ReviewForm
              key={`${alert.id}-${alert.review_status}`}
              alert={alert}
              monitor={m}
              onSaved={(updated) => {
                setAlert(updated)
                m.updateAlert(updated)
                notify(
                  'Решение сохранено' +
                    (m.settings.mode === 'demo' ? ' в этом браузере.' : ' на сервере.'),
                )
              }}
            />
            <p className="page-note">
              Оценка показывает признаки риска и не устанавливает факт нарушения.
            </p>
          </aside>
        </div>
      )}
    </>
  )
}
function ReviewForm({
  alert,
  monitor: m,
  onSaved,
}: {
  alert: Alert
  monitor: Monitor
  onSaved: (a: Alert) => void
}) {
  const [note, setNote] = useState(alert.reviewer_note)
  const [status, setStatus] = useState<Review>(alert.review_status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      onSaved(await saveReview(m.settings, alert.id, status, note))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить решение.')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Panel title="Решение аналитика" description="Сохраните итог ручной проверки">
      <form className="review-form" onSubmit={submit}>
        <label htmlFor="review-status">Статус проверки</label>
        <select
          id="review-status"
          value={status}
          onChange={(e) => setStatus(e.target.value as Review)}
          disabled={saving || alert.status !== 'PROCESSED'}
        >
          {Object.entries(reviewLabels).map(([value, label]) => (
            <option value={value} key={value}>
              {label}
            </option>
          ))}
        </select>
        <label htmlFor="review-note">
          Комментарий <span>(необязательно)</span>
        </label>
        <textarea
          id="review-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Что удалось установить при проверке?"
          maxLength={2000}
          rows={4}
          disabled={saving || alert.status !== 'PROCESSED'}
        />
        <small>{note.length} / 2000</small>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="button button-primary" disabled={saving || alert.status !== 'PROCESSED'}>
          {saving ? (
            <RefreshCw size={16} className="spin" />
          ) : status === 'REVIEWED' ? (
            <CheckCheck size={16} />
          ) : (
            <CheckCircle2 size={16} />
          )}
          {saving ? 'Сохраняем…' : 'Сохранить решение'}
        </button>
        <p className="form-caption">
          <FileText size={13} />
          {alert.status !== 'PROCESSED'
            ? 'Дождитесь успешного анализа сообщения.'
            : m.settings.mode === 'demo'
              ? 'Демо: решение сохранится в этом браузере.'
              : 'Решение будет отправлено в Backend API.'}
        </p>
      </form>
    </Panel>
  )
}
