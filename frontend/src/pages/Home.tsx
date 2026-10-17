import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { LayoutDashboard, LogOut, User } from 'lucide-react'
import { LogoMark } from '@/components/AuthLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useSession } from '@/hooks/useSession'

export default function HomePage() {
  const { user, logout } = useSession()
  const navigate = useNavigate()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-dvh bg-slate-50 dark:bg-slate-950">
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/80 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <LogoMark className="h-7 w-7 text-brand-600 dark:text-brand-400" />
            <span className="font-display text-base font-semibold tracking-tight">Igris</span>
          </Link>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 py-1 pl-1 pr-3 dark:border-slate-700 dark:bg-slate-900 sm:flex">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-accent-500 text-xs font-semibold text-white">
                {(user?.username || '?').slice(0, 1).toUpperCase()}
              </div>
              <span className="max-w-[120px] truncate text-sm font-medium">
                {user?.username || 'User'}
              </span>
            </div>
            <Button variant="ghost" size="sm" onClick={onLogout} className="text-slate-600 dark:text-slate-300">
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mx-auto max-w-lg text-center"
        >
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-brand text-white shadow-lg shadow-brand-500/20">
            <LayoutDashboard className="h-8 w-8" />
          </div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
            Welcome{user ? `, ${user.username}` : ''}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            Your workspace is ready. Dashboards, broker connections, and analytics will
            appear here in upcoming releases.
          </p>

          <Card className="mt-8 border-dashed">
            <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
              <User className="h-5 w-5 text-slate-400" />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Nothing to show yet — check back soon.
              </p>
            </CardContent>
          </Card>
        </motion.div>
      </main>
    </div>
  )
}
