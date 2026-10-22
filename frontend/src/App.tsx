import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  ChartNoAxesCombined,
  CircleHelp,
  Database,
  Inbox,
  Network,
  Settings2,
  X,
} from 'lucide-react'
import { motion, MotionConfig } from 'motion/react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { BrandIntro, shouldShowIntro } from './components/BrandIntro'
import { Empty, Logo } from './components/ui'
import { Dashboard } from './pages/Dashboard'
import { AlertDetail } from './pages/AlertDetail'
import { Chats } from './pages/Chats'
import { Analytics } from './pages/Analytics'
import { SettingsPage } from './pages/Settings'
import { useMonitor } from './lib/useMonitor'
import { addDemoAlert } from './data/demo'
const Graph = lazy(() => import('./pages/Graph').then((module) => ({ default: module.Graph })))
const Scene3D = lazy(() =>
  import('./components/Scene3D').then((module) => ({ default: module.Scene3D })),
)

export default function App() {
  const monitor = useMonitor()
  const [intro, setIntro] = useState(shouldShowIntro)
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 801px)').matches)
  const [toast, setToast] = useState('')
  const help = useRef<HTMLDialogElement>(null)
  const location = useLocation()
  useEffect(() => {
    const query = window.matchMedia('(min-width: 801px)')
    const update = () => setWide(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 5000)
    return () => clearTimeout(timer)
  }, [toast])
  function addMessage() {
    addDemoAlert()
    monitor.refresh()
    setToast('Демо-сообщение добавлено.')
  }
  return (
    <MotionConfig reducedMotion="user">
      <BrandIntro active={intro} onComplete={() => setIntro(false)} />
      <div className="app-shell">
        <a className="skip-link" href="#main">
          К основному содержимому
        </a>
        <header className="app-header">
          <div className="header-inner">
            <Link to="/" className="brand-link" aria-label="Blue — мониторинг">
              <Logo />
            </Link>
            <div className="workspace-name">
              <span>Рабочее пространство</span>
              <strong>SafeNet KZ</strong>
            </div>
            <nav className="primary-nav" aria-label="Главная навигация">
              <NavLink to="/" end>
                <Inbox size={18} /> Входящие
              </NavLink>
              <NavLink to="/chats" aria-label="Чаты и источники">
                <Database size={18} /> Источники
              </NavLink>
              <NavLink to="/graph">
                <Network size={18} /> Граф связей
              </NavLink>
              <NavLink to="/analytics">
                <ChartNoAxesCombined size={18} /> Аналитика
              </NavLink>
            </nav>
            <NavLink to="/settings" className="sidebar-settings">
              <Settings2 size={18} /> Настройки
            </NavLink>
            <div className="sidebar-art">
              {wide && !intro && (
                <Suspense fallback={null}>
                  <Scene3D />
                </Suspense>
              )}
              <p>Сигналы. Контекст. Решение.</p>
            </div>
            <div className="header-tools">
              <span className={`source-pill ${monitor.settings.mode}`}>
                {monitor.settings.mode === 'demo' ? 'Деморежим' : 'Backend API'}
              </span>
              <button
                className="icon-button"
                aria-label="О проекте"
                onClick={() => help.current?.showModal()}
              >
                <CircleHelp size={18} />
              </button>
              <NavLink to="/settings" className="icon-button" aria-label="Настройки">
                <Settings2 size={18} />
              </NavLink>
            </div>
          </div>
        </header>
        <div className="workspace-bar">
          <span>
            Рабочее пространство <i>/</i>{' '}
            {location.pathname.startsWith('/alerts')
              ? 'Проверка сообщения'
              : {
                  '/': 'Входящие',
                  '/chats': 'Источники',
                  '/analytics': 'Аналитика',
                  '/graph': 'Граф связей',
                  '/settings': 'Настройки',
                }[location.pathname] || 'Blue'}
          </span>
          <span className="workspace-status">
            <i /> {monitor.settings.mode === 'demo' ? 'Деморежим' : 'Backend API'}
          </span>
        </div>
        <main id="main" tabIndex={-1}>
          <motion.div
            key={location.pathname}
            className="route-view"
            initial={{ opacity: 0.75, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            <Suspense
              fallback={<div className="loading-state">Загружаем рабочее пространство…</div>}
            >
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
                <Route path="/graph" element={<Graph monitor={monitor} />} />
                <Route
                  path="/settings"
                  element={<SettingsPage monitor={monitor} notify={setToast} />}
                />
                <Route
                  path="*"
                  element={
                    <Empty
                      title="Страница не найдена"
                      text="Вернитесь к списку сообщений."
                      action={
                        <Link className="button button-primary" to="/">
                          К мониторингу
                        </Link>
                      }
                    />
                  }
                />
              </Routes>
            </Suspense>
          </motion.div>
        </main>
        <footer className="app-footer">
          <span>
            Blue <span className="footer-separator">/</span> SafeNet KZ
          </span>
          <span>Окончательное решение — за аналитиком.</span>
        </footer>
        <dialog ref={help} className="help-dialog" aria-labelledby="help-title">
          <div className="dialog-heading">
            <Logo />
            <button
              className="icon-button"
              aria-label="Закрыть окно"
              onClick={() => help.current?.close()}
            >
              <X size={19} />
            </button>
          </div>
          <h2 id="help-title">О Blue</h2>
          <p>Проверка признаков финансовых пирамид в сообщениях Telegram и импортах WhatsApp.</p>
          <p>
            В деморежиме сообщения синтетические. Оценки подготовлены для демонстрации; решение
            принимает аналитик.
          </p>
          <button
            className="button replay-intro"
            onClick={() => {
              help.current?.close()
              setIntro(true)
            }}
          >
            Посмотреть заставку <ArrowRight size={16} />
          </button>
          <Link className="text-button" to="/settings" onClick={() => help.current?.close()}>
            Настройки подключения
          </Link>
        </dialog>
        {toast && (
          <div className="toast" role="status">
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
    </MotionConfig>
  )
}
