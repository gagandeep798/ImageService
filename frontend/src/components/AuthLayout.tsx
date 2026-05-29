import s from '../styles/AuthLayout.module.css'

export default function AuthLayout({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={s.page}>
      <div className={s.card}>
        <h1 className={s.title}>{title}</h1>
        {children}
      </div>
    </div>
  )
}
