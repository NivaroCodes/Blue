import { ArrowUpRight, Check, MessageSquare } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EvidenceText, Platform, RiskBadge } from './ui'
import { reasonLabels, time } from '../lib/model'
import type { Alert } from '../lib/model'
import type { Settings } from '../lib/model'
import { PrivateImage } from './PrivateImage'

export function EvidencePreview({ alert, demo, settings }: { alert?: Alert; demo: boolean; settings: Settings }) {
  return (
    <aside className="focus-panel" aria-label="Предпросмотр сообщения" data-alert-id={alert?.id}>
      <div className="focus-heading">
        <h2>В фокусе</h2>
        <MessageSquare size={18} />
      </div>
      {!alert ? (
        <p className="focus-empty">
          Выберите сообщение из текущей выборки, чтобы увидеть контекст и причины оценки.
        </p>
      ) : (
        <>
          <div className="focus-source">
            <span className={`source-avatar ${alert.platform}`}>
              <Platform platform={alert.platform} />
            </span>
            <div>
              <strong>{alert.chat_name}</strong>
              <span>
                <Platform platform={alert.platform} label /> · {time(alert.timestamp)}
              </span>
            </div>
          </div>
          <div className="focus-score">
            <span>Оценка риска</span>
            <div>
              <strong>{alert.risk_score ?? '—'}</strong>
              <span>/ 100</span>
            </div>
            <RiskBadge level={alert.risk_level} />
          </div>
          <div className="focus-text">
            <h3>Исходное сообщение</h3>
            <blockquote>
              <EvidenceText
                text={alert.text}
                evidence={alert.reasons.map((reason) => reason.evidence)}
              />
            </blockquote>
          </div>
          {alert.image_url && <PrivateImage imageUrl={alert.image_url} settings={settings} />}
          <div className="focus-reasons">
            <h3>Почему это риск</h3>
            {alert.reasons.length ? (
              alert.reasons.map((reason, index) => (
                <div key={`${reason.code}-${index}`}>
                  <Check size={14} />
                  <span>{reasonLabels[reason.code] || reason.code}</span>
                </div>
              ))
            ) : (
              <p>
                {alert.status === 'PROCESSED'
                  ? 'Существенные признаки не выделены.'
                  : 'Объяснение появится после обработки.'}
              </p>
            )}
          </div>
          <Link className="focus-open" to={`/alerts/${encodeURIComponent(alert.id)}`}>
            Открыть проверку <ArrowUpRight size={17} />
          </Link>
        </>
      )}
      <p className="focus-disclaimer">
        {demo ? 'Синтетические примеры. ' : ''}Оценка — сигнал для проверки. Решение принимает
        аналитик.
      </p>
    </aside>
  )
}
