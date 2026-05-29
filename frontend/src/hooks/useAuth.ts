import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { getAuthUser, login, logout, register, confirmRegistration, type AuthUser } from '../lib/auth'

interface AuthState {
  user: AuthUser | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string) => Promise<string>
  confirm: (email: string, code: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function useAuthState(): AuthState {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getAuthUser().then(setUser).finally(() => setLoading(false))
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    await login(email, password)
    setUser(await getAuthUser())
  }, [])

  const signUp = useCallback(async (email: string, password: string) => {
    return register(email, password)
  }, [])

  const confirm = useCallback(async (email: string, code: string) => {
    await confirmRegistration(email, code)
  }, [])

  const signOut = useCallback(async () => {
    await logout()
    setUser(null)
  }, [])

  return { user, loading, signIn, signUp, confirm, signOut }
}
