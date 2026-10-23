import { useState } from 'react'
import { ArrowUpRight, Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Empty, ErrorBox, Platform } from '../components/ui'
import type { Monitor } from '../lib/useMonitor'
import { sourceSummaries } from '../lib/analytics'

export function Chats({ monitor: m }: { monitor: Monitor }) {
  const [query, setQuery] = useState('')
  const chats = sourceSummaries(m.alerts)
    .filter((c) => c.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Источники</h1>
          <p>Telegram и WhatsApp · {chats.length} в текущей выборке</p>
        </div>
        <Link className="button" to="/settings">
          Настроить подключение <ArrowUpRight size={15} />
        </Link>
      </div>
      {m.error && <ErrorBox message={m.error} retry={m.refresh} />}
      <div className="section-toolbar">
        <label className="search-field">
          <Search size={17} />
          <input
            aria-label="Поиск чатов"
            placeholder="Найти источник"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      <div className="source-list">
        {chats.map((chat) => (
          <article className="chat-card" key={chat.key}>
            <div className="source-identity">
              <span className="source-symbol">
                <Platform platform={chat.platform} />
              </span>
              <div>
                <h2>{chat.name}</h2>
                <span className="subtle">
                  {chat.platform === 'telegram' ? 'Telegram' : 'WhatsApp'}
                </span>
              </div>
            </div>
            <div className="source-numbers">
              <span>{chat.count} сообщений</span>
              <span className={chat.stats.by_level.HIGH ? 'high-text' : 'subtle'}>
                {chat.stats.by_level.HIGH} высокого риска
              </span>
            </div>
            <Link
              className="chat-card-link"
              to={`/?chat=${encodeURIComponent(chat.id)}&platform=${chat.platform}&period=all`}
              aria-label={`Открыть сообщения — ${chat.name}`}
            >
              Открыть сообщения <ArrowUpRight size={16} />
            </Link>
          </article>
        ))}
      </div>
      {!chats.length && (
        <Empty
          title={m.loading ? 'Загружаем источники…' : 'Чаты не найдены'}
          text="Измените поисковый запрос."
        />
      )}
      <p className="page-note">
        {m.settings.mode === 'demo'
          ? 'Все источники демонстрационные.'
          : 'Источники из подключённого API.'}{' '}
        Работаем с разрешёнными и обезличенными данными.
      </p>
    </>
  )
}
