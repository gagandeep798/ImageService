import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import s from '../styles/AppLayout.module.css'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  return (
    <div className={s.page}>
      <nav className={s.nav}>
        <Link to="/" className={s.logo}>Images</Link>
        <div className={s.navRight}>
          <span className={s.username}>{user?.username}</span>
          <button onClick={handleSignOut} className={s.signOut}>Sign out</button>
        </div>
      </nav>
      <main className={s.main}>{children}</main>
    </div>
  )
}
