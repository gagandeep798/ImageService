import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthLayout from '../components/AuthLayout'
import s from '../styles/form.module.css'

export default function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await signIn(email, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Sign in">
      <form onSubmit={handleSubmit}>
        <div className={s.field}>
          <label className={s.label}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} required className={s.input} />
        </div>
        <div className={s.field}>
          <label className={s.label}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} required className={s.input} />
        </div>
        {error && <div className={s.error}>{error}</div>}
        <button type="submit" disabled={loading} className={s.btn}>
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
      <div className={s.footer}>No account? <Link to="/signup">Sign up</Link></div>
    </AuthLayout>
  )
}
