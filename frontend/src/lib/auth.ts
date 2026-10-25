type AuthSession = {
  access_token: string
  refresh_token: string
  expires_at: number
  user: { id: string; email?: string }
}

const SESSION_KEY = 'blue.auth.session.v1'
const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

export const authConfigured = Boolean(supabaseUrl && publishableKey)

function readSession(): AuthSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthSession
    if (
      typeof parsed.access_token !== 'string' ||
      typeof parsed.refresh_token !== 'string' ||
      typeof parsed.expires_at !== 'number' ||
      typeof parsed.user?.id !== 'string'
    ) {
      sessionStorage.removeItem(SESSION_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function writeSession(session: AuthSession) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY)
}

export async function signOut() {
  const session = readSession()
  clearSession()
  if (!session || !authConfigured) return
  try {
    await fetch(`${supabaseUrl}/auth/v1/logout`, {
      method: 'POST',
      headers: {
        apikey: publishableKey,
        Authorization: `Bearer ${session.access_token}`,
      },
      signal: AbortSignal.timeout(5_000),
    })
  } catch {
    // Local session is already cleared; server revocation is best effort.
  }
}

async function authRequest(path: string, body: Record<string, string>) {
  if (!authConfigured) throw new Error('Вход не настроен: добавьте публичные переменные Supabase в сборку сайта.')
  const response = await fetch(`${supabaseUrl}/auth/v1/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', apikey: publishableKey },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(12_000),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = response.status === 400 || response.status === 401
      ? 'Не удалось войти. Проверьте email и пароль.'
      : 'Сервис входа временно недоступен. Попробуйте ещё раз.'
    throw new Error(message)
  }
  return data
}

function normalizeSession(data: Record<string, any>): AuthSession {
  if (!data.access_token || !data.refresh_token || !data.user?.id)
    throw new Error('Supabase вернул неполную сессию. Попробуйте войти ещё раз.')
  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: Math.floor(Date.now() / 1000) + Number(data.expires_in || 3600),
    user: { id: data.user.id, email: data.user.email },
  }
}

export async function signIn(email: string, password: string) {
  const data = await authRequest('token?grant_type=password', { email, password })
  const session = normalizeSession(data)
  writeSession(session)
  return session
}

async function refreshSession(current: AuthSession): Promise<AuthSession | null> {
  try {
    const data = await authRequest('token?grant_type=refresh_token', {
      refresh_token: current.refresh_token,
    })
    const session = normalizeSession(data)
    writeSession(session)
    return session
  } catch {
    clearSession()
    return null
  }
}

export async function restoreSession() {
  const current = readSession()
  if (!current) return null
  if (current.expires_at <= Math.floor(Date.now() / 1000) + 60) return refreshSession(current)
  return current
}

export async function getAccessToken(forceRefresh = false) {
  let session = readSession()
  if (!session) return null
  if (forceRefresh || session.expires_at <= Math.floor(Date.now() / 1000) + 60) {
    session = await refreshSession(session)
  }
  return session?.access_token || null
}
