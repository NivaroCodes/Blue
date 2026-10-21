import { useState } from 'react'
import {
  ArrowUpRight,
  CircleAlert,
  Link2,
  MessageSquare,
  Search,
  Settings2,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Monitor } from '../lib/useMonitor'
import { Empty, ErrorBox, Panel, Platform } from '../components/ui'

export function Chats({ monitor: m }: { monitor: Monitor }) {
  const [query, setQuery] = useState('')
  const chats = Array.from(new Set(m.alerts.map((a) => a.chat_id)))
    .map((id) => {
      const alerts = m.alerts.filter((a) => a.chat_id === id)
      return {
        id,
        name: alerts[0].chat_name,
        platform: alerts[0].platform,
        total: alerts.length,
        high: alerts.filter((a) => a.risk_level === 'HIGH').length,
        medium: alerts.filter((a) => a.risk_level === 'MEDIUM').length,
        low: alerts.filter((a) => a.risk_level === 'LOW').length,
        pending: alerts.filter((a) => a.status !== 'PROCESSED').length,
      }
    })
    .filter((c) => c.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => b.high - a.high)
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span className="tiny-blue-line" /> ИСТОЧНИКИ ДАННЫХ
          </div>
          <h1>
            Чаты под наблюдением<span className="heading-dot">.</span>
          </h1>
          <p>Сообщения и сигналы в контексте каждого сообщества.</p>
        </div>
        <Link className="button button-primary" to="/settings">
          <Settings2 size={16} /> Подключение API
        </Link>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="source-summary">
        <div>
          <span className="summary-icon">
            <MessageSquare size={23} />
          </span>
          <strong>{chats.length}</strong>
          <span>источников в выборке</span>
        </div>
        <div>
          <span className="summary-icon">
            <Link2 size={23} />
          </span>
          <strong>2</strong>
          <span>поддерживаемые платформы</span>
        </div>
        <div>
          <span className="summary-icon">
            <ShieldCheck size={23} />
          </span>
          <span>
            Только разрешённые источники
            <br />
            <small>Открытые, синтетические или обезличенные данные</small>
          </span>
        </div>
      </div>
      <div className="section-toolbar">
        <h2>Все источники</h2>
        <label className="search-field">
          <Search size={17} />
          <input
            aria-label="Поиск чатов"
            placeholder="Найти чат…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      <div className="chat-grid">
        {chats.map((chat) => (
          <Panel className="chat-card" key={chat.id}>
            <div className="chat-card-top">
              <span className="chat-avatar">
                <MessageSquare size={23} />
              </span>
              <Platform platform={chat.platform} label />
            </div>
            <h3>{chat.name}</h3>
            <span className="chat-source-caption">
              <span className="status-dot" />
              {m.settings.mode === 'demo' ? 'Демонстрационный источник' : 'Источник из Backend API'}
            </span>
            <div className="chat-count">
              <strong>{chat.total}</strong>
              <span>сообщений в выборке</span>
            </div>
            <div className="chat-risk-bar">
              {[
                { count: chat.high, level: 'high' },
                { count: chat.medium, level: 'medium' },
                { count: chat.low, level: 'low' },
                { count: chat.pending, level: 'neutral' },
              ].map((item) => (
                <span
                  key={item.level}
                  className={item.level}
                  style={{ width: `${(item.count / chat.total) * 100}%` }}
                />
              ))}
            </div>
            <div className="chat-levels">
              <span>
                <i className="legend-dot high" />
                Высокий <b>{chat.high}</b>
              </span>
              <span>
                <i className="legend-dot medium" />
                Средний <b>{chat.medium}</b>
              </span>
              <span>
                <i className="legend-dot low" />
                Низкий <b>{chat.low}</b>
              </span>
            </div>
            <Link
              className="chat-card-link"
              to={`/?chat=${encodeURIComponent(chat.id)}&period=all`}
            >
              Открыть сообщения <ArrowUpRight size={16} />
            </Link>
          </Panel>
        ))}
      </div>
      {!chats.length && (
        <Empty
          title={m.loading ? 'Загружаем источники…' : 'Чаты не найдены'}
          text="Источники появляются из сообщений, полученных через API или деморежим."
        />
      )}
      <div className="source-policy">
        <CircleAlert size={22} />
        <div>
          <h3>Источник начинается с разрешения</h3>
          <p>
            Telegram подключается через бота команды в разрешённой тестовой группе. Для WhatsApp в
            MVP предусмотрен демонстрационный импорт на стороне backend. Blue не собирает сообщения
            из произвольных закрытых чатов.
          </p>
        </div>
      </div>
    </>
  )
}
