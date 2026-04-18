const ACCESS = 'access_token'
const REFRESH = 'refresh_token'

/** Обновить access за ~2 минуты до истечения, чтобы не ловить 401 на каждом запросе. */
const ACCESS_REFRESH_SKEW_SEC = 120

const tokenListeners = new Set<() => void>()

/** Вызывается при любом изменении access/refresh в storage (логин, refresh, выход). */
export function onAccessTokenChanged(cb: () => void): () => void {
  tokenListeners.add(cb)
  return () => tokenListeners.delete(cb)
}

function notifyAccessTokenChanged() {
  for (const cb of tokenListeners) cb()
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH)
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS, access)
  localStorage.setItem(REFRESH, refresh)
  notifyAccessTokenChanged()
}

export function clearTokens() {
  localStorage.removeItem(ACCESS)
  localStorage.removeItem(REFRESH)
  notifyAccessTokenChanged()
}

export function isLoggedIn(): boolean {
  return !!getAccessToken()
}

const apiBase = '/api/v1'

export type ApiError = { error: { code: string; message: string } }

function parseJwtPayload(token: string): { exp?: number } | null {
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4))
    const json = atob(b64 + pad)
    return JSON.parse(json) as { exp?: number }
  } catch {
    return null
  }
}

function accessExpiresWithin(access: string, seconds: number): boolean {
  const exp = parseJwtPayload(access)?.exp
  if (exp == null || typeof exp !== 'number') return false
  const now = Math.floor(Date.now() / 1000)
  return exp - now <= seconds
}

let refreshFlight: Promise<boolean> | null = null

/**
 * Одна параллельная попытка refresh на всё приложение — иначе на бэкенде ротация refresh
 * инвалидирует второй одновременный запрос.
 */
export async function refreshSession(): Promise<boolean> {
  if (refreshFlight) return refreshFlight

  refreshFlight = (async (): Promise<boolean> => {
    const rt = getRefreshToken()
    if (!rt) {
      clearTokens()
      return false
    }
    const res = await fetch(`${apiBase}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    const data = (await res.json().catch(() => ({}))) as {
      access_token?: string
      refresh_token?: string
    }
    if (!res.ok || !data.access_token || !data.refresh_token) {
      clearTokens()
      return false
    }
    setTokens(data.access_token, data.refresh_token)
    return true
  })().finally(() => {
    refreshFlight = null
  })

  return refreshFlight
}

/** Перед API и стримингом: не даём протухнуть access, пока refresh ещё жив. */
export async function ensureAccessTokenFresh(): Promise<void> {
  const rt = getRefreshToken()
  if (!rt) return

  const access = getAccessToken()
  if (!access) {
    await refreshSession()
    return
  }
  if (accessExpiresWithin(access, ACCESS_REFRESH_SKEW_SEC)) {
    await refreshSession()
  }
}

async function apiFetchOnce(path: string, init: RequestInit, afterRefresh: boolean): Promise<Response> {
  const headers = new Headers(init.headers)
  const t = getAccessToken()
  if (t) {
    headers.set('Authorization', `Bearer ${t}`)
  }
  const res = await fetch(`${apiBase}${path}`, { ...init, headers })
  if (
    res.status === 401 &&
    !afterRefresh &&
    path !== '/auth/refresh' &&
    getRefreshToken()
  ) {
    const ok = await refreshSession()
    if (ok) return apiFetchOnce(path, init, true)
  }
  return res
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  await ensureAccessTokenFresh()
  return apiFetchOnce(path, init, false)
}

export async function loginRequest(username: string, password: string) {
  const res = await fetch(`${apiBase}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = data as ApiError
    throw new Error(err.error?.message ?? res.statusText)
  }
  return data as {
    access_token: string
    refresh_token: string
    user: { id: string; username: string }
  }
}

export async function registerRequest(username: string, password: string) {
  const res = await fetch(`${apiBase}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = data as ApiError
    throw new Error(err.error?.message ?? res.statusText)
  }
  return data as {
    access_token: string
    refresh_token: string
    user: { id: string; username: string }
  }
}
