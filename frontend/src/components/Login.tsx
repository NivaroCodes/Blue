import { useState } from 'react'
import type { FormEvent } from 'react'
import { LockKeyhole, RefreshCw, ShieldCheck } from 'lucide-react'
import { authConfigured, signIn } from '../lib/auth'

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState('info@gmail.com')
  const [password, setPassword] = useState('info67')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await signIn(email.trim(), password)
      setPassword('')
      onSignedIn()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось войти. Попробуйте ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-screen">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand"><ShieldCheck size={24} /><span>Blue · SafeNet KZ</span></div>
        <span className="eyebrow">ЗАЩИЩЁННОЕ РАБОЧЕЕ ПРОСТРАНСТВО</span>
        <h1 id="login-title">Вход аналитика</h1>
        <p className="login-copy">Войдите под аккаунтом команды, чтобы открыть сообщения и аналитику.</p>
        {!authConfigured && (
          <div className="login-setup" role="alert">
            Для сайта не заданы <code>VITE_SUPABASE_URL</code> и <code>VITE_SUPABASE_PUBLISHABLE_KEY</code>.
            Добавьте их в переменные сборки Cloudflare Pages и пересоберите сайт.
          </div>
        )}
        <form className="login-form" onSubmit={submit}>
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@example.com"
            disabled={busy || !authConfigured}
          />
          <label htmlFor="login-password">Пароль</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Пароль аккаунта Supabase Auth"
            disabled={busy || !authConfigured}
          />
          {error && <p className="login-error" role="alert">{error}</p>}
          <button className="button button-primary login-submit" disabled={busy || !authConfigured}>
            {busy ? <RefreshCw className="spin" size={17} /> : <LockKeyhole size={17} />}
            {busy ? 'Входим…' : 'Войти'}
          </button>
        </form>
        <p className="login-footnote">Доступ выдаётся существующим пользователям команды. Регистрация отключена.</p>
      </section>
    </main>
  )
}
