import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthLayout from '../components/AuthLayout'
import s from '../styles/form.module.css'

export default function SignupPage() {
  const { signUp } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await signUp(email, password, displayName)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Create account">
      <form onSubmit={handleRegister}>
        <div className={s.field}>
          <label className={s.label}>Display name</label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)} required minLength={1} maxLength={100} className={s.input} />
        </div>
        <div className={s.field}>
          <label className={s.label}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} required className={s.input} />
        </div>
        <div className={s.field}>
          <label className={s.label}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} className={s.input} />
          <div className={s.hint}>Min 8 characters</div>
        </div>
        {error && <div className={s.error}>{error}</div>}
        <button type="submit" disabled={loading} className={s.btn}>{loading ? 'Creating...' : 'Create account'}</button>
      </form>
      <div className={s.footer}>Already have an account? <Link to="/login">Sign in</Link></div>
    </AuthLayout>
  )
}
