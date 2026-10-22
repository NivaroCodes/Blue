import { KrakenMark } from './components/KrakenMark'
import { BrandIntro, rememberIntro, shouldShowIntro } from './components/BrandIntro'
import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  Bell,
  BookOpen,
  ChartNoAxesCombined,
  ChevronRight,
  CircleHelp,
  Database,
  LayoutDashboard,
  Menu,
  MessageSquare,
  Radio,
  Settings2,
  ShieldCheck,
  X,
} from 'lucide-react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useMonitor } from './lib/useMonitor'
import { Logo } from './components/ui'
import { Dashboard } from './pages/Dashboard'
import { AlertDetail } from './pages/AlertDetail'
import { Chats } from './pages/Chats'
import { Analytics } from './pages/Analytics'
import { SettingsPage } from './pages/Settings'
import { Empty } from './components/ui'
import { addDemoAlert } from './data/demo'

const navigation = [
  { to: '/', label: 'Мониторинг', icon: LayoutDashboard, end: true },
  { to: '/chats', label: 'Чаты и источники', icon: MessageSquare },
  { to: '/analytics', label: 'Аналитика', icon: ChartNoAxesCombined },
]
export default function App() {
  const monitor = useMonitor()
  const [intro, setIntro] = useState(shouldShowIntro)
  function finishIntro() {
    rememberIntro()
    setIntro(false)
  }
  const [menu, setMenu] = useState(false)
  const [notifications, setNotifications] = useState(false)
  const [toast, setToast] = useState('')
  const help = useRef<HTMLDialogElement>(null)
  const location = useLocation()
  useEffect(() => {
    setMenu(false)
    setNotifications(false)
    window.scrollTo(0, 0)
  }, [location.pathname])
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenu(false)
        setNotifications(false)
      }
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [])
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(''), 5000)
      return () => clearTimeout(timer)
    }
  }, [toast])
  const label = location.pathname.startsWith('/alerts')
    ? 'Детали сообщения'
    : [...navigation, { to: '/settings', label: 'Настройки' }].find(
        (n) => n.to === location.pathname,
      )?.label || 'Страница не найдена'
  function addMessage() {
    addDemoAlert()
    monitor.refresh()
    setToast('Демосообщение добавлено в ленту. Все оценки заранее заданы для показа интерфейса.')
  }
  return (
    <>
      <BrandIntro active={intro} onComplete={finishIntro} />
      <div className="app-shell">
        <a className="skip-link" href="#main">
          К основному содержимому
        </a>
        {menu && (
          <button
            className="sidebar-scrim"
            aria-label="Закрыть навигацию"
            onClick={() => setMenu(false)}
          />
        )}
        <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
          <Link to="/" className="brand-link" aria-label="Kraken — мониторинг">
            <Logo />
          </Link>
          <div className="workspace-chip">
            <span className="workspace-icon">
              <ShieldCheck size={19} />
            </span>
            <div>
              <b>SafeNet KZ</b>
              <span>Рабочее пространство</span>
            </div>
            <ChevronRight size={15} />
          </div>
          <p className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
          <nav aria-label="Главная навигация">
            {navigation.map(({ icon: Icon, ...item }) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{item.label}</span>
                {item.to === '/' && (
                  <span className="nav-count">{monitor.stats.by_level.HIGH}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="track-card">
              <span className="track-icon">
                <KrakenMark />
              </span>
              <span className="track-label">SAFENET HACKATHON</span>
              <h3>
                Замечать раньше.
                <br />
                Защищать лучше.
              </h3>
              <p>Трек 03 · Стоп-пирамида</p>
              <div className="track-line">
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
            <NavLink
              to="/settings"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Settings2 size={19} />
              <span>Настройки</span>
            </NavLink>
            <button className="nav-link help-link" onClick={() => help.current?.showModal()}>
              <CircleHelp size={19} />
              <span>О проекте</span>
              <ArrowRight size={15} />
            </button>
            <div className="profile">
              <div className="avatar">KR</div>
              <div>
                <b>Команда Kraken</b>
                <span>Пространство аналитика</span>
              </div>
              <span className="online-dot" />
            </div>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumb">
              <button
                className="icon-button mobile-menu"
                aria-label="Открыть навигацию"
                aria-expanded={menu}
                onClick={() => setMenu(!menu)}
              >
                <Menu size={20} />
              </button>
              <span className="breadcrumb-home">Рабочее пространство</span>
              <ChevronRight size={14} />
              <b>{label}</b>
            </div>
            <div className="topbar-actions">
              <span className={`source-pill ${monitor.settings.mode}`}>
                <span className="status-dot" />
                {monitor.settings.mode === 'demo' ? 'Деморежим' : 'Backend API'}
              </span>
              <div className="notification-wrap">
                <button
                  className="icon-button notification-button"
                  aria-label={`Уведомления: ${monitor.newCount} новых`}
                  aria-expanded={notifications}
                  onClick={() => {
                    setNotifications(!notifications)
                    if (notifications) monitor.setNewCount(0)
                  }}
                >
                  <Bell size={19} />
                  {monitor.newCount > 0 && <span className="notification-dot" />}
                </button>
                {notifications && (
                  <div className="notification-popover">
                    <b>Обновления ленты</b>
                    <p>
                      {monitor.error
                        ? 'Подключение к API требует внимания.'
                        : monitor.newCount
                          ? `Новых сообщений: ${monitor.newCount}. Они уже доступны в мониторинге.`
                          : 'Новых уведомлений нет. Лента обновляется каждые 10 секунд при включённом live-режиме.'}
                    </p>
                    <button
                      className="text-button"
                      onClick={() => {
                        monitor.setNewCount(0)
                        setNotifications(false)
                      }}
                    >
                      Отметить прочитанным
                    </button>
                  </div>
                )}
              </div>
              <div className="avatar top-avatar">KR</div>
            </div>
          </header>
          <main id="main" tabIndex={-1}>
            <Routes>
              <Route
                path="/"
                element={<Dashboard monitor={monitor} onDemoMessage={addMessage} />}
              />
              <Route
                path="/alerts/:id"
                element={<AlertDetail monitor={monitor} notify={setToast} />}
              />
              <Route path="/chats" element={<Chats monitor={monitor} />} />
              <Route path="/analytics" element={<Analytics monitor={monitor} />} />
              <Route
                path="/settings"
                element={<SettingsPage monitor={monitor} notify={setToast} />}
              />
              <Route
                path="*"
                element={
                  <Empty
                    title="Эта страница не найдена"
                    text="Перейдите к мониторингу, чтобы продолжить работу."
                    action={
                      <Link className="button button-primary" to="/">
                        К мониторингу
                      </Link>
                    }
                  />
                }
              />
            </Routes>
          </main>
          <footer className="app-footer">
            <span>
              <ShieldCheck size={14} /> Kraken помогает находить признаки. Решение принимает
              человек.
            </span>
            <span>
              SafeNet KZ <span className="footer-dot">·</span> MVP 2026
            </span>
          </footer>
        </div>
        <dialog ref={help} className="help-dialog">
          <div className="dialog-heading">
            <Logo />
            <button
              className="icon-button"
              aria-label="Закрыть окно"
              onClick={() => help.current?.close()}
            >
              <X size={20} />
            </button>
          </div>
          <span className="eyebrow">SAFENET KZ · ТРЕК 03</span>
          <h2>
            Помогаем заметить
            <br />
            подозрительное вовремя.
          </h2>
          <p>
            Kraken — рабочее пространство для проверки признаков финансовых пирамид в Telegram и
            демонстрационных импортах WhatsApp.
          </p>
          <div className="help-steps">
            <p>
              <Database size={20} /> Сообщения из разрешённых источников
            </p>
            <p>
              <Radio size={20} /> Объяснимые оценки и фрагменты текста
            </p>
            <p>
              <ShieldCheck size={20} /> Финальное решение за аналитиком
            </p>
          </div>
          <p className="subtle">
            В деморежиме все сообщения синтетические, а оценки заданы вручную. Точность AI на этих
            данных не измеряется.
          </p>
          <Link
            className="button button-primary"
            to="/settings"
            onClick={() => help.current?.close()}
          >
            <BookOpen size={16} /> Настройки подключения
          </Link>
          <button
            className="button replay-intro"
            onClick={() => {
              help.current?.close()
              setIntro(true)
            }}
          >
            Посмотреть заставку <ArrowRight size={16} />
          </button>
        </dialog>
        {toast && (
          <div className="toast" role="status">
            <ShieldCheck size={20} />
            <span>{toast}</span>
            <button
              className="icon-button"
              aria-label="Закрыть уведомление"
              onClick={() => setToast('')}
            >
              <X size={16} />
            </button>
          </div>
        )}
      </div>
    </>
  )
}
