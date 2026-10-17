import { motion } from 'framer-motion'
import { LayoutDashboard, User } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Card, CardContent } from '@/components/ui/card'
import { useSession } from '@/hooks/useSession'

export default function HomePage() {
  const { user } = useSession()

  return (
    <div className="min-h-dvh bg-slate-50 dark:bg-slate-950">
      <AppHeader />

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
