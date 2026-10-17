import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import jsQR from 'jsqr'
import {
  Cable,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { api, type Connection, type ConnectionsConfig, type Provider, type TestResult } from '@/lib/api'

const STATUS_META: Record<Connection['status'], { label: string; cls: string }> = {
  connected: { label: 'Connected', cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  needs_auth: { label: 'Needs auth', cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
  error: { label: 'Error', cls: 'bg-red-500/10 text-red-600 dark:text-red-400' },
  never_authed: { label: 'Never authed', cls: 'bg-slate-500/10 text-slate-500 dark:text-slate-400' },
}

const PROVIDER_BADGE: Record<Provider, { text: string; cls: string }> = {
  fyers: { text: 'FY', cls: 'from-sky-500 to-blue-600' },
  groww: { text: 'GW', cls: 'from-orange-400 to-amber-600' },
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/** Extract base32 secret from an otpauth:// QR payload. */
function secretFromOtpauth(raw: string): string | null {
  const s = raw.trim()
  if (!s.toLowerCase().startsWith('otpauth://')) return null
  try {
    const u = new URL(s)
    const secret = u.searchParams.get('secret')
    return secret ? secret.toUpperCase().replace(/\s+/g, '') : null
  } catch {
    return null
  }
}

/* ------------------------------- Add form ------------------------------- */

function AddConnectionForm({
  config,
  onCreated,
  onClose,
}: {
  config: ConnectionsConfig
  onCreated: () => void
  onClose: () => void
}) {
  const [provider, setProvider] = useState<Provider>('fyers')
  const [label, setLabel] = useState('')
  const [appId, setAppId] = useState('')
  const [secret, setSecret] = useState('')
  const [totpQr, setTotpQr] = useState('')
  const [qrNotice, setQrNotice] = useState('')
  const [showHelp, setShowHelp] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const help = config.help[provider]
  const isFyers = provider === 'fyers'
  const steps = help?.steps.map((s) => s.replace('{redirect}', config.redirect_uri)) ?? []

  async function onQrFile(file: File | undefined) {
    if (!file) return
    setQrNotice('')
    setError('')
    try {
      const url = URL.createObjectURL(file)
      const img = new Image()
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('Could not read image file'))
        img.src = url
      })
      const canvas = document.createElement('canvas')
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas not available')
      ctx.drawImage(img, 0, 0)
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      const code = jsQR(data.data, data.width, data.height)
      const sec = code?.data ? secretFromOtpauth(code.data) : null
      if (!sec) throw new Error('No TOTP QR code found in that image')
      setSecret(sec)
      setQrNotice(`QR scanned — TOTP secret extracted from ${file.name}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'QR scan failed')
    }
  }

  function onQrPaste(value: string) {
    setTotpQr(value)
    const sec = secretFromOtpauth(value)
    if (sec) {
      setSecret(sec)
      setQrNotice('QR content recognized — TOTP secret extracted')
    } else if (value.trim()) {
      setQrNotice('')
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.post('/api/connections', {
        provider,
        label,
        app_id: appId,
        app_secret: secret,
        totp_qr: isFyers ? '' : totpQr,
      })
      onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <Card className="border-brand-500/30">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-base font-semibold">Add trading connection</h2>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </div>

          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Broker</Label>
              <Select value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>
                <option value="fyers">Fyers</option>
                <option value="groww">Groww</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Label</Label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={isFyers ? 'Fyers main account' : 'Groww main account'}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{isFyers ? 'App ID' : 'TOTP Token'}</Label>
              <Input
                value={appId}
                onChange={(e) => setAppId(e.target.value)}
                placeholder={isFyers ? 'e.g. ABC12345X' : 'Token shown after "Generate TOTP token"'}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label>{isFyers ? 'App Secret' : 'TOTP Secret'}</Label>
              <Input
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={isFyers ? 'Secret key from dashboard' : 'Base32 secret from QR / authenticator'}
                required={isFyers || (!secret && !totpQr)}
              />
            </div>
            {!isFyers && (
              <div className="space-y-1.5 sm:col-span-2">
                <Label>TOTP QR Code</Label>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    value={totpQr}
                    onChange={(e) => onQrPaste(e.target.value)}
                    placeholder="Paste QR content (otpauth://…) or upload the QR image →"
                    className="h-11 max-w-md flex-1"
                  />
                  <label className="inline-flex h-11 cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800">
                    Scan QR image
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        void onQrFile(e.target.files?.[0])
                        e.target.value = ''
                      }}
                    />
                  </label>
                </div>
                {qrNotice && (
                  <p className="text-xs text-emerald-600 dark:text-emerald-400">{qrNotice}</p>
                )}
              </div>
            )}

            {error && (
              <p className="text-sm text-red-600 sm:col-span-2">{error}</p>
            )}

            <div className="flex items-center justify-between gap-3 sm:col-span-2">
              <button
                type="button"
                onClick={() => setShowHelp((v) => !v)}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
              >
                <ExternalLink className="h-4 w-4" />
                Where do I find these? ({showHelp ? 'hide' : 'show'})
              </button>
              <Button type="submit" disabled={busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Continue
              </Button>
            </div>

            {showHelp && help && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/60 sm:col-span-2">
                <p className="mb-2 text-sm font-semibold">{help.title}</p>
                <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
                  {steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
                <a
                  href={help.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
                >
                  {help.url_label} <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </motion.div>
  )
}

/* ------------------------------- Card ------------------------------- */

function ConnectionCard({
  conn,
  manualFlow,
  onChanged,
}: {
  conn: Connection
  manualFlow: boolean
  onChanged: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [test, setTest] = useState<TestResult | null>(null)
  const [error, setError] = useState('')
  const [pasteMode, setPasteMode] = useState(false)
  const [authUrl, setAuthUrl] = useState('')
  const [code, setCode] = useState('')

  const badge = STATUS_META[conn.status]
  const pBadge = PROVIDER_BADGE[conn.provider]
  const connected = conn.status === 'connected'

  async function run<T>(name: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy(name)
    setError('')
    try {
      return await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
      return null
    } finally {
      setBusy(null)
    }
  }

  async function onTest() {
    const res = await run('test', () => api.post<TestResult>(`/api/connections/${conn.id}/test`))
    if (res) setTest(res)
    onChanged()
  }

  async function onGrowwConnect() {
    const res = await run('connect', () =>
      api.post<{ detail: string }>(`/api/connections/${conn.id}/connect-groww`),
    )
    if (res) onChanged()
  }

  async function onFyersAuth() {
    const res = await run('auth', () =>
      api.post<{ url: string; manual: boolean }>(`/api/connections/${conn.id}/auth-url`),
    )
    if (!res) return
    if (res.manual || manualFlow) {
      setAuthUrl(res.url)
      setPasteMode(true)
    } else {
      window.location.href = res.url
    }
  }

  async function submitCode() {
    await run('complete', () =>
      api.post(`/api/connections/${conn.id}/complete-auth`, { code: code.trim() }),
    )
    setPasteMode(false)
    setCode('')
    onChanged()
  }

  async function onReauthTime(value: string) {
    await run('patch', () => api.patch(`/api/connections/${conn.id}`, { reauth_time: value }))
    onChanged()
  }

  async function onDelete() {
    if (!window.confirm(`Delete "${conn.label}"?`)) return
    await run('delete', () => api.del(`/api/connections/${conn.id}`))
    onChanged()
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <Card className="h-full">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${pBadge.cls} text-sm font-bold text-white`}
              >
                {pBadge.text}
              </div>
              <div>
                <p className="font-display text-sm font-semibold leading-tight">{conn.label}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {conn.provider === 'fyers' ? 'Fyers' : 'Groww'} · {conn.app_id || '—'}
                </p>
              </div>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${badge.cls}`}>
              {badge.label}
            </span>
          </div>

          <div className="mt-4 flex flex-wrap gap-1.5">
            {conn.tools.slice(0, 5).map((t) => (
              <span
                key={t}
                className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400"
              >
                {t}
              </span>
            ))}
            {conn.tools.length > 5 && (
              <span className="px-1 py-0.5 text-[11px] text-slate-400">
                +{conn.tools.length - 5} more
              </span>
            )}
          </div>

          <dl className="mt-4 space-y-1.5 text-xs text-slate-500 dark:text-slate-400">
            <div className="flex justify-between">
              <dt>Token expires</dt>
              <dd>{fmtTime(conn.expires_at)}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt>Auto re-auth time</dt>
              <dd>
                <input
                  type="time"
                  defaultValue={conn.reauth_time}
                  onBlur={(e) => e.target.value !== conn.reauth_time && onReauthTime(e.target.value)}
                  className="rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-xs dark:border-slate-700"
                />
              </dd>
            </div>
            <div className="flex justify-between">
              <dt>Last re-auth</dt>
              <dd>{fmtTime(conn.last_reauth_at)}</dd>
            </div>
          </dl>

          {conn.last_error && conn.status !== 'connected' && (
            <p className="mt-3 break-words rounded-lg bg-red-500/10 px-2.5 py-1.5 text-xs text-red-600 dark:text-red-400">
              {conn.last_error}
            </p>
          )}

          {test && (
            <p
              className={
                'mt-3 flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs ' +
                (test.success
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                  : 'bg-red-500/10 text-red-600 dark:text-red-400')
              }
            >
              {test.success ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              Test: {test.message}
            </p>
          )}
          {error && <p className="mt-3 text-xs text-red-600 dark:text-red-400">{error}</p>}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={onTest}
              disabled={busy !== null}
            >
              {busy === 'test' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Test
            </Button>
            {conn.provider === 'groww' ? (
              <Button size="sm" onClick={onGrowwConnect} disabled={busy !== null}>
                {busy === 'connect' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : connected ? (
                  <RefreshCw className="h-3.5 w-3.5" />
                ) : null}
                {connected ? 'Refresh login' : 'Connect'}
              </Button>
            ) : (
              <Button size="sm" onClick={onFyersAuth} disabled={busy !== null}>
                {busy === 'auth' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ExternalLink className="h-3.5 w-3.5" />
                )}
                {connected ? 'Re-authorize' : 'Authorize'}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={onDelete}
              disabled={busy !== null}
              className="ml-auto text-red-500 hover:text-red-600"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>

          {pasteMode && (
            <div className="mt-4 rounded-xl border border-brand-500/30 bg-brand-500/5 p-3">
              <p className="mb-2 text-xs font-medium">
                1. Open the Fyers authorization page (new tab) and approve:
                <br />
                <a
                  href={authUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-flex items-center gap-1 break-all text-brand-600 hover:underline dark:text-brand-400"
                >
                  {authUrl} <ExternalLink className="h-3 w-3" />
                </a>
              </p>
              <p className="mb-2 text-xs">
                2. You will land on a URL like{' '}
                <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">
                  .../callback?code=XXXX
                </code>{' '}
                — copy the <b>code</b> and paste it here:
              </p>
              <div className="flex gap-2">
                <Input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="auth code"
                  className="h-8"
                />
                <Button size="sm" onClick={submitCode} disabled={!code.trim() || busy !== null}>
                  {busy === 'complete' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Submit
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  )
}

/* ------------------------------- Page ------------------------------- */

export default function ConnectionsPage() {
  const [config, setConfig] = useState<ConnectionsConfig | null>(null)
  const [list, setList] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')
  const [params] = useSearchParams()

  const refresh = useCallback(async () => {
    try {
      const [cfg, conns] = await Promise.all([
        api.get<ConnectionsConfig>('/api/connections/config'),
        api.get<Connection[]>('/api/connections'),
      ])
      setConfig(cfg)
      setList(conns)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <div className="min-h-dvh bg-slate-50 dark:bg-slate-950">
      <AppHeader />

      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8 flex flex-wrap items-end justify-between gap-4"
        >
          <div>
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-brand text-white shadow-lg shadow-brand-500/20">
              <Cable className="h-6 w-6" />
            </div>
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
              Trading Connections
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              Connect your brokers so Igris can read positions, holdings and orders.
              Credentials are encrypted at rest; tokens refresh every morning at your
              configured re-auth time.
            </p>
          </div>
          <Button onClick={() => setAdding((v) => !v)}>
            <Plus className="h-4 w-4" />
            Add connection
          </Button>
        </motion.div>

        {params.get('fyers') === 'ok' && (
          <p className="mb-4 rounded-xl bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-600 dark:text-emerald-400">
            Fyers authorization complete — connection updated.
          </p>
        )}
        {error && (
          <p className="mb-4 rounded-xl bg-red-500/10 px-4 py-2.5 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        {config && adding && (
          <AddConnectionForm
            config={config}
            onCreated={refresh}
            onClose={() => setAdding(false)}
          />
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        ) : list.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 p-12 text-center">
              <Cable className="h-6 w-6 text-slate-400" />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No broker connections yet. Add your first Fyers or Groww account above.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {list.map((c) => (
              <ConnectionCard
                key={c.id}
                conn={c}
                manualFlow={config?.manual_flow ?? false}
                onChanged={refresh}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
