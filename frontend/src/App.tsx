import { useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { SessionProvider, useSession } from '@/hooks/useSession'
import { useTheme } from '@/hooks/useTheme'
import { api } from '@/lib/api'
import SetupPage from '@/pages/Setup'
import LoginPage from '@/pages/Login'
import ForgotPasswordPage from '@/pages/ForgotPassword'
import ResetPasswordPage from '@/pages/ResetPassword'
import HomePage from '@/pages/Home'

function Spinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
    </div>
  )
}

/** Redirects to /setup when app is not installed (except on setup/auth pages that handle it). */
function InstallGate({ children }: { children: ReactNode }) {
  const [installed, setInstalled] = useState<boolean | null>(null)
  const location = useLocation()

  useEffect(() => {
    let cancelled = false
    api
      .get<{ installed: boolean }>('/api/health')
      .then((h) => {
        if (!cancelled) setInstalled(h.installed)
      })
      .catch(() => {
        if (!cancelled) setInstalled(true) // assume installed on error to avoid loops
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (installed === null) return <Spinner />

  const path = location.pathname
  const onSetup = path === '/setup'

  if (!installed) {
    // Not installed → force wizard. Allow /setup and reset-password (token may be valid from prior install edge).
    if (onSetup || path.startsWith('/reset-password')) return <>{children}</>
    return <Navigate to="/setup" replace />
  }

  // Installed → /setup self-redirects inside SetupPage; block re-entry via route guard below.
  if (onSetup) return <Navigate to="/" replace />

  return <>{children}</>
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useSession()
  if (loading) return <Spinner />
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: ReactNode }) {
  const { user, loading } = useSession()
  if (loading) return <Spinner />
  if (user) return <Navigate to="/" replace />
  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route
        path="/login"
        element={
          <RedirectIfAuthed>
            <LoginPage />
          </RedirectIfAuthed>
        }
      />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <HomePage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  useTheme()
  return (
    <SessionProvider>
      <BrowserRouter>
        <InstallGate>
          <AppRoutes />
        </InstallGate>
      </BrowserRouter>
    </SessionProvider>
  )
}
