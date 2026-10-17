import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Eye, EyeOff, Loader2, Mail, Send, ShieldCheck, Sparkles, UserPlus } from 'lucide-react'
import { AuthLayout } from '@/components/AuthLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select } from '@/components/ui/select'
import { api, type SetupState, type SmtpConfig, type SmtpTestResult } from '@/lib/api'
import { cn } from '@/lib/utils'

const STEPS = [
  { key: 'welcome', label: 'Welcome', icon: Sparkles },
  { key: 'admin', label: 'Admin user', icon: UserPlus },
  { key: 'smtp', label: 'Email', icon: Mail },
  { key: 'review', label: 'Finish', icon: Check },
] as const

function passwordIssues(pw: string): string[] {
  const issues: string[] = []
  if (pw.length < 8) issues.push('At least 8 characters')
  if (!/[A-Z]/.test(pw)) issues.push('One uppercase letter')
  if (!/[a-z]/.test(pw)) issues.push('One lowercase letter')
  if (!/[0-9]/.test(pw)) issues.push('One number')
  if (!/[^A-Za-z0-9]/.test(pw)) issues.push('One symbol')
  return issues
}

export default function SetupPage() {
  const [step, setStep] = useState(0)
  const [state, setState] = useState<SetupState | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [setupToken, setSetupToken] = useState('')

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)

  const [smtp, setSmtp] = useState<SmtpConfig>({
    host: '',
    port: 587,
    security: 'STARTTLS',
    username: '',
    password: '',
    from_name: 'Igris',
    from_email: '',
  })
  const [skipSmtp, setSkipSmtp] = useState(false)
  const [testResult, setTestResult] = useState<SmtpTestResult | null>(null)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api
      .get<SetupState>('/api/setup/state')
      .then((s) => {
        setState(s)
        if (s.installed) window.location.assign('/')
      })
      .catch(() => {
        // 404 = already installed
        window.location.assign('/')
      })
  }, [])

  const issues = useMemo(() => passwordIssues(password), [password])
  const pwStrength = 100 - issues.length * 20

  async function nextFromWelcome(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.post('/api/setup/step1', { app_name: 'Igris', setup_token: setupToken })
      setStep(1)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  async function nextFromAdmin(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    if (issues.length) {
      setError('Password does not meet requirements')
      return
    }
    setBusy(true)
    try {
      await api.post('/api/setup/step2', {
        username,
        email,
        password,
        confirm_password: confirm,
      })
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  async function sendTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await api.post<SmtpTestResult>('/api/setup/smtp-test', smtp)
      setTestResult(result)
    } catch (err) {
      setTestResult({ success: false, message: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setTesting(false)
    }
  }

  function nextFromSmtp() {
    setError('')
    setSkipSmtp(false)
    setStep(3)
  }

  function skipFromSmtp() {
    setSkipSmtp(true)
    setStep(3)
  }

  async function finish() {
    setBusy(true)
    setError('')
    try {
      await api.post('/api/setup/finish', { smtp: skipSmtp ? null : smtp })
      // Hard reload: InstallGate cached installed=false; cookies are set so /me works on reload.
      window.location.assign('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    )
  }

  const progress = ((step + 1) / STEPS.length) * 100

  return (
    <AuthLayout title="Set up Igris" subtitle="A few quick steps to get you running.">
      <div className="mb-8">
        <div className="mb-3 flex items-center justify-between text-xs font-medium text-slate-500 dark:text-slate-400">
          <span>
            Step {step + 1} of {STEPS.length}
          </span>
          <span>{STEPS[step].label}</span>
        </div>
        <Progress value={progress} />
        <div className="mt-3 flex justify-between">
          {STEPS.map((s, i) => {
            const Icon = s.icon
            return (
              <div
                key={s.key}
                className={cn(
                  'flex flex-col items-center gap-1 text-[10px] font-medium',
                  i <= step ? 'text-brand-600 dark:text-brand-400' : 'text-slate-400'
                )}
              >
                <div
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-full border transition-colors',
                    i < step
                      ? 'border-brand-500 bg-brand-500 text-white'
                      : i === step
                        ? 'border-brand-500 bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-400'
                        : 'border-slate-200 dark:border-slate-700'
                  )}
                >
                  {i < step ? <Check className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
                </div>
                <span className="hidden sm:block">{s.label}</span>
              </div>
            )
          })}
        </div>
      </div>

      {error && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </motion.div>
      )}

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        >
          {step === 0 && (
            <Card className="border-0 shadow-none">
              <CardContent className="p-0">
                <form onSubmit={nextFromWelcome} className="space-y-5">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Welcome to Igris. Let&apos;s get your workspace set up — it only takes a minute.
                  </p>

                  {state.setup_token_required && (
                    <div className="space-y-2">
                      <Label htmlFor="setup_token">
                        <span className="inline-flex items-center gap-1.5">
                          <ShieldCheck className="h-3.5 w-3.5" /> Setup token
                        </span>
                      </Label>
                      <Input
                        id="setup_token"
                        type="password"
                        value={setupToken}
                        onChange={(e) => setSetupToken(e.target.value)}
                        required
                      />
                    </div>
                  )}

                  <Button type="submit" variant="brand" size="lg" className="w-full" disabled={busy}>
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Get started</>}
                  </Button>
                </form>
              </CardContent>
            </Card>
          )}

          {step === 1 && (
            <form onSubmit={nextFromAdmin} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  minLength={3}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPw ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    minLength={8}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    aria-label={showPw ? 'Hide password' : 'Show password'}
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <div className="mt-2">
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all duration-300',
                        pwStrength >= 80
                          ? 'bg-brand-500'
                          : pwStrength >= 60
                            ? 'bg-amber-500'
                            : 'bg-red-500'
                      )}
                      style={{ width: `${Math.max(pwStrength, 8)}%` }}
                    />
                  </div>
                  <ul className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                    {[
                      'At least 8 characters',
                      'One uppercase letter',
                      'One lowercase letter',
                      'One number',
                      'One symbol',
                    ].map((rule) => {
                      const ok = !issues.includes(rule)
                      return (
                        <li
                          key={rule}
                          className={cn(
                            'flex items-center gap-1.5',
                            ok ? 'text-brand-600 dark:text-brand-400' : 'text-slate-400'
                          )}
                        >
                          <Check className={cn('h-3 w-3', ok ? 'opacity-100' : 'opacity-30')} />
                          {rule}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm">Confirm password</Label>
                <Input
                  id="confirm"
                  type={showPw ? 'text' : 'password'}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  minLength={8}
                  required
                />
              </div>
              <div className="flex gap-3">
                <Button type="button" variant="outline" onClick={() => setStep(0)} className="flex-1">
                  Back
                </Button>
                <Button type="submit" variant="brand" className="flex-1" disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Continue'}
                </Button>
              </div>
            </form>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  nextFromSmtp()
                }}
                className="space-y-4"
              >
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div className="space-y-2 sm:col-span-2">
                    <Label htmlFor="smtp_host">SMTP host</Label>
                    <Input
                      id="smtp_host"
                      value={smtp.host}
                      onChange={(e) => setSmtp({ ...smtp, host: e.target.value })}
                      placeholder="smtp.example.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="smtp_port">Port</Label>
                    <Input
                      id="smtp_port"
                      type="number"
                      value={smtp.port}
                      onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="smtp_security">Security</Label>
                    <Select
                      id="smtp_security"
                      value={smtp.security}
                      onChange={(e) =>
                        setSmtp({ ...smtp, security: e.target.value as SmtpConfig['security'] })
                      }
                    >
                      <option value="None">None</option>
                      <option value="STARTTLS">STARTTLS</option>
                      <option value="SSL">SSL</option>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="smtp_username">Username</Label>
                    <Input
                      id="smtp_username"
                      value={smtp.username}
                      onChange={(e) => setSmtp({ ...smtp, username: e.target.value })}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="smtp_password">Password</Label>
                  <Input
                    id="smtp_password"
                    type="password"
                    value={smtp.password}
                    onChange={(e) => setSmtp({ ...smtp, password: e.target.value })}
                  />
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="from_name">From name</Label>
                    <Input
                      id="from_name"
                      value={smtp.from_name}
                      onChange={(e) => setSmtp({ ...smtp, from_name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="from_email">From email</Label>
                    <Input
                      id="from_email"
                      type="email"
                      value={smtp.from_email}
                      onChange={(e) => setSmtp({ ...smtp, from_email: e.target.value })}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={sendTest}
                    disabled={testing || !smtp.host || !smtp.from_email}
                    className="flex-1"
                  >
                    {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Send test email
                  </Button>
                  <Button type="submit" variant="brand" className="flex-1">
                    Continue
                  </Button>
                </div>
                <Button type="button" variant="ghost" onClick={skipFromSmtp} className="w-full text-slate-500">
                  Skip for now
                </Button>
              </form>

              {testResult && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn(
                    'rounded-lg border px-4 py-3 text-sm',
                    testResult.success
                      ? 'border-brand-200 bg-brand-50 text-brand-800 dark:border-brand-900 dark:bg-brand-950 dark:text-brand-200'
                      : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300'
                  )}
                >
                  {testResult.success ? '✓ ' : '✕ '}
                  {testResult.message}
                </motion.div>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6">
              <Card>
                <CardContent className="space-y-4 p-5">
                  <SummaryRow label="Admin username" value={username} />
                  <SummaryRow label="Admin email" value={email} />
                  <SummaryRow label="SMTP" value={skipSmtp ? 'Skipped' : smtp.host || 'Not set'} />
                </CardContent>
              </Card>

              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStep(skipSmtp ? 0 : 2)}
                  className="flex-1"
                  disabled={busy}
                >
                  Back
                </Button>
                <Button type="button" variant="brand" onClick={finish} className="flex-1" disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Finish setup'}
                </Button>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </AuthLayout>
  )
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-medium">{value || '—'}</span>
    </div>
  )
}
