import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthLayout from '../components/AuthLayout'
import s from '../styles/form.module.css'

type Step = 'register' | 'confirm'

export default function SignupPage() {
  const { signUp, confirm } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('register')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const nextStep = await signUp(email, password)
      if (nextStep === 'CONFIRM_SIGN_UP') setStep('confirm')
      else navigate('/login')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await confirm(email, code)
      navigate('/login')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirmation failed')
    } finally {
      setLoading(false)
    }
  }

  if (step === 'confirm') {
    return (
      <AuthLayout title="Verify email">
        <p className={s.subtext}>Check your email for a verification code.</p>
        <form onSubmit={handleConfirm}>
          <div className={s.field}>
            <label className={s.label}>Verification code</label>
            <input value={code} onChange={e => setCode(e.target.value)} required className={s.input} />
          </div>
          {error && <div className={s.error}>{error}</div>}
          <button type="submit" disabled={loading} className={s.btn}>{loading ? 'Verifying...' : 'Verify'}</button>
        </form>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Create account">
      <form onSubmit={handleRegister}>
        <div className={s.field}>
          <label className={s.label}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} required className={s.input} />
        </div>
        <div className={s.field}>
          <label className={s.label}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={12} className={s.input} />
          <div className={s.hint}>Min 12 chars, uppercase, number, symbol</div>
        </div>
        {error && <div className={s.error}>{error}</div>}
        <button type="submit" disabled={loading} className={s.btn}>{loading ? 'Creating...' : 'Create account'}</button>
      </form>
      <div className={s.footer}>Already have an account? <Link to="/login">Sign in</Link></div>
    </AuthLayout>
  )
}
