const ACCESS = 'access_token'
const REFRESH = 'refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS)
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS, access)
  localStorage.setItem(REFRESH, refresh)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS)
  localStorage.removeItem(REFRESH)
}

export function isLoggedIn(): boolean {
  return !!getAccessToken()
}

const apiBase = '/api/v1'

export type ApiError = { error: { code: string; message: string } }

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const t = getAccessToken()
  if (t) {
    headers.set('Authorization', `Bearer ${t}`)
  }
  return fetch(`${apiBase}${path}`, { ...init, headers })
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
