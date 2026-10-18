import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Bot, Cable, LayoutDashboard, LogOut, Sparkles } from 'lucide-react'
import { LogoMark } from '@/components/AuthLayout'
import { Button } from '@/components/ui/button'
import { useSession } from '@/hooks/useSession'

const TABS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/connections', label: 'Trading Connection', icon: Cable },
  { to: '/llm', label: 'LLM', icon: Bot },
  { to: '/igris', label: 'Igris', icon: Sparkles },
]

export function AppHeader() {
  const { user, logout } = useSession()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/80 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link to="/" className="flex shrink-0 items-center gap-2.5">
          <LogoMark className="h-8 w-8 rounded-lg" />
          <span className="font-display text-base font-semibold tracking-tight">Igris</span>
        </Link>

        <nav className="flex items-center gap-1">
          {TABS.map(({ to, label, icon: Icon }) => {
            const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
            return (
              <Link
                key={to}
                to={to}
                className={
                  'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition ' +
                  (active
                    ? 'bg-gradient-to-r from-brand-500/10 to-accent-500/10 text-brand-600 dark:text-brand-300'
                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200')
                }
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="flex shrink-0 items-center gap-3">
          <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 py-1 pl-1 pr-3 dark:border-slate-700 dark:bg-slate-900 sm:flex">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-accent-500 text-xs font-semibold text-white">
              {(user?.username || '?').slice(0, 1).toUpperCase()}
            </div>
            <span className="max-w-[120px] truncate text-sm font-medium">
              {user?.username || 'User'}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogout}
            className="text-slate-600 dark:text-slate-300"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Logout</span>
          </Button>
        </div>
      </div>
    </header>
  )
}
