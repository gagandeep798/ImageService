const ACCESS_TOKEN_KEY = 'is_access_token'
const REFRESH_TOKEN_KEY = 'is_refresh_token'
const USER_ID_KEY = 'is_user_id'

export interface AuthUser {
  userId: string
  username: string
}

async function post(path: string, body: object) {
  const res = await fetch(`/v1${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await res.json()
  if (!res.ok) {
    throw new Error(json?.error?.message ?? `Request failed: ${res.status}`)
  }
  return json.data
}

export async function login(email: string, password: string) {
  const data = await post('/auth/login', { email, password })
  sessionStorage.setItem(ACCESS_TOKEN_KEY, data.access_token)
  sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token)
  sessionStorage.setItem(USER_ID_KEY, data.user_id)
}

export async function register(email: string, password: string, displayName: string) {
  const data = await post('/auth/signup', { email, password, display_name: displayName })
  sessionStorage.setItem(ACCESS_TOKEN_KEY, data.access_token)
  sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token)
  sessionStorage.setItem(USER_ID_KEY, data.user_id)
}

export async function logout() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  sessionStorage.removeItem(USER_ID_KEY)
}

export async function getAuthUser(): Promise<AuthUser | null> {
  const userId = sessionStorage.getItem(USER_ID_KEY)
  const token = sessionStorage.getItem(ACCESS_TOKEN_KEY)
  if (!userId || !token) return null
  return { userId, username: userId }
}

export async function getAccessToken(): Promise<string | null> {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY)
}
