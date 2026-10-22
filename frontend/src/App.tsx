import { useEffect, useRef, useState } from 'react'
import { ArrowRight, CircleHelp, Settings2, X } from 'lucide-react'
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

export default function App() {
  const monitor = useMonitor()
  const [intro, setIntro] = useState(shouldShowIntro)
  const [toast, setToast] = useState('')
  const help = useRef<HTMLDialogElement>(null)
  const location = useLocation()
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
    <>
      <BrandIntro active={intro} onComplete={() => setIntro(false)} />
      <div className="app-shell">
        <a className="skip-link" href="#main">
          К основному содержимому
        </a>
        <header className="app-header">
          <div className="header-inner">
            <Link to="/" className="brand-link" aria-label="Kraken — мониторинг">
              <Logo />
            </Link>
            <nav className="primary-nav" aria-label="Главная навигация">
              <NavLink to="/" end>
                Входящие
              </NavLink>
              <NavLink to="/chats" aria-label="Чаты и источники">
                Источники
              </NavLink>
              <NavLink to="/analytics">Аналитика</NavLink>
            </nav>
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
        <main id="main" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Dashboard monitor={monitor} onDemoMessage={addMessage} />} />
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
        </main>
        <footer className="app-footer">
          <span>
            Kraken <span className="footer-separator">/</span> SafeNet KZ
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
          <h2 id="help-title">О Kraken</h2>
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
    </>
  )
}
