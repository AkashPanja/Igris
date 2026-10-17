import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface AuthLayoutProps {
  children: ReactNode
  title: string
  subtitle?: string
}

export function AuthLayout({ children, title, subtitle }: AuthLayoutProps) {
  return (
    <div className="min-h-dvh w-full lg:grid lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-brand lg:flex lg:flex-col lg:justify-between lg:p-10">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -left-32 -top-32 h-96 w-96 rounded-full bg-brand-400/20 blur-3xl" />
          <div className="absolute -bottom-40 -right-24 h-[28rem] w-[28rem] rounded-full bg-accent-400/20 blur-3xl" />
          <motion.div
            className="absolute inset-0 opacity-[0.07]"
            style={{
              backgroundImage:
                'linear-gradient(rgba(255,255,255,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.4) 1px, transparent 1px)',
              backgroundSize: '48px 48px',
            }}
            animate={{ backgroundPosition: ['0px 0px', '48px 48px'] }}
            transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
          />
        </div>

        <motion.div
          className="relative z-10 flex items-center gap-3"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <LogoMark className="h-9 w-9 text-white" />
          <span className="font-display text-xl font-semibold text-white">Igris</span>
        </motion.div>

        <motion.div
          className="relative z-10 max-w-md"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15 }}
        >
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium text-white/90 backdrop-blur">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-300 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-300" />
            </span>
            Trading workspace
          </div>
          <h2 className="font-display text-4xl font-bold leading-tight text-white">
            Your markets,
            <br />
            <span className="text-brand-200">beautifully organized.</span>
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-white/70">
            Igris brings your brokerage, portfolio, and insights into one calm, modern
            dashboard. Built for focus — not clutter.
          </p>
        </motion.div>

        <div className="relative z-10 text-xs text-white/50">
          Secure · Self-hosted · Encrypted at rest
        </div>
      </div>

      <div className="flex min-h-dvh flex-col justify-center bg-white px-6 py-12 dark:bg-slate-950 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-md">
          <motion.div
            className="mb-8 lg:hidden"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="mb-6 flex items-center gap-3">
              <LogoMark className="h-8 w-8 text-brand-600 dark:text-brand-400" />
              <span className="font-display text-lg font-semibold">Igris</span>
            </div>
            <div className="rounded-2xl bg-gradient-brand p-5 text-white">
              <p className="font-display text-lg font-semibold leading-snug">
                Your markets, beautifully organized.
              </p>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.1 }}
          >
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
              {title}
            </h1>
            {subtitle && (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
            )}
          </motion.div>

          <motion.div
            className="mt-8"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            {children}
          </motion.div>
        </div>
      </div>
    </div>
  )
}

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={cn('h-6 w-6', className)} aria-hidden>
      <defs>
        <linearGradient id="igris-g" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="currentColor" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0.5" />
        </linearGradient>
      </defs>
      <path
        d="M16 2L28 9V23L16 30L4 23V9L16 2Z"
        stroke="url(#igris-g)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M16 10V22M11 13.5L21 18.5M21 13.5L11 18.5"
        stroke="url(#igris-g)"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}
