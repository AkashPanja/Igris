import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Bot,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  XCircle,
} from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import {
  api,
  type LlmConfig,
  type LlmConnection,
  type LlmProvider,
  type LlmProviderInfo,
  type ModelsResponse,
  type TestResult,
} from '@/lib/api'

const BADGES: Record<string, { text: string; cls: string }> = {
  openai: { text: 'AI', cls: 'from-emerald-500 to-teal-600' },
  anthropic: { text: 'AN', cls: 'from-orange-500 to-amber-600' },
  gemini: { text: 'GM', cls: 'from-blue-500 to-indigo-600' },
  groq: { text: 'GQ', cls: 'from-fuchsia-500 to-purple-600' },
  openrouter: { text: 'OR', cls: 'from-slate-500 to-slate-700' },
  cloudflare: { text: 'CF', cls: 'from-amber-500 to-orange-600' },
  custom: { text: 'CX', cls: 'from-sky-500 to-cyan-600' },
}

/* --------------------------- Add / Edit form --------------------------- */

function LlmForm({
  config,
  initial,
  onSaved,
  onClose,
}: {
  config: LlmConfig
  initial?: LlmConnection | null
  onSaved: (id: string) => void
  onClose: () => void
}) {
  const isEdit = Boolean(initial)
  const [providerId, setProviderId] = useState<LlmProvider>(initial?.provider ?? 'openai')
  const [label, setLabel] = useState(initial?.label ?? '')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '')
  const [model, setModel] = useState(initial?.model ?? '')
  const [customModel, setCustomModel] = useState('')
  const [loadedModels, setLoadedModels] = useState<string[] | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelSource, setModelSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const info: LlmProviderInfo =
    config.providers.find((p) => p.id === providerId) || config.providers[0]
  const modelValue = model === '__custom__' ? customModel.trim() : model
  const modelOptions = Array.from(
    new Set([...(loadedModels ?? info?.models ?? []), ...(initial?.model ? [initial.model] : [])]),
  )

  async function loadModels() {
    setLoadingModels(true)
    try {
      const res = await api.post<ModelsResponse>('/api/llm/models',
        isEdit && !apiKey.trim()
          ? { conn_id: initial!.id }
          : { provider: providerId, api_key: apiKey, base_url: baseUrl },
      )
      setLoadedModels(res.models)
      setModelSource(res.source)
      if (!isEdit && res.models.length && model !== '__custom__') setModel(res.models[0])
    } catch {
      setModelSource('load failed')
    } finally {
      setLoadingModels(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (isEdit) {
        await api.patch(`/api/llm/${initial!.id}`, {
          label,
          model: modelValue,
          base_url: baseUrl,
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        })
        onSaved(initial!.id)
      } else {
        const res = await api.post<{ id: string }>('/api/llm', {
          provider: providerId,
          label,
          api_key: apiKey,
          base_url: baseUrl,
          model: modelValue,
        })
        onSaved(res.id)
      }
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
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-base font-semibold">
              {isEdit ? `Edit LLM connection · ${initial!.label}` : 'Add LLM connection'}
            </h2>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </div>

          <form onSubmit={submit} className="grid min-w-0 gap-4 sm:grid-cols-2">
            <div className="min-w-0 space-y-1.5">
              <Label>Provider</Label>
              {isEdit ? (
                <p className="flex h-10 items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-sm dark:border-slate-700 dark:bg-slate-900">
                  {info?.label ?? providerId}
                </p>
              ) : (
                <Select
                  value={providerId}
                  onChange={(e) => {
                    setProviderId(e.target.value as LlmProvider)
                    const p = config.providers.find((x) => x.id === e.target.value)
                    setModel(p?.models[0] || '__custom__')
                    setCustomModel('')
                    setLoadedModels(null)
                    setModelSource('')
                  }}
                >
                  {config.providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              )}
            </div>
            <div className="min-w-0 space-y-1.5">
              <Label>Label</Label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={`${info?.label || 'LLM'} main`}
              />
            </div>
            <div className="min-w-0 space-y-1.5">
              <Label>API Key {isEdit && <span className="text-slate-400">(unchanged if blank)</span>}</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={isEdit ? '••••••••' : info?.key_hint || 'api key'}
                required={!isEdit}
              />
              {info?.docs && (
                <a
                  href={info.docs}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                >
                  Get a key <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
            <div className="min-w-0 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label>Model</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={loadingModels || (!apiKey && !isEdit)}
                  onClick={loadModels}
                >
                  {loadingModels ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Load models
                </Button>
              </div>
              <Select
                value={model === '__custom__' || (model && !modelOptions.includes(model)) ? '__custom__' : model}
                onChange={(e) => {
                  if (e.target.value === '__custom__') {
                    setModel('__custom__')
                    if (model && model !== '__custom__') setCustomModel(model)
                  } else {
                    setModel(e.target.value)
                    setCustomModel('')
                  }
                }}
              >
                {!model && <option value="" disabled>select…</option>}
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value="__custom__">Custom…</option>
              </Select>
              {modelSource && <p className="text-[10px] text-slate-400">{modelSource}</p>}
            </div>
            {model === '__custom__' && (
              <div className="min-w-0 space-y-1.5 sm:col-span-2">
                <Label>Custom model id</Label>
                <Input
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="model id exactly as the provider expects"
                  required
                />
              </div>
            )}
            {info?.base_url_required && (
              <div className="min-w-0 space-y-1.5 sm:col-span-2">
                <Label>Base URL (OpenAI-compatible)</Label>
                <Input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://your-gateway.example.com/v1"
                  required
                />
              </div>
            )}

            {error && <p className="break-words text-sm text-red-600 sm:col-span-2">{error}</p>}

            <div className="flex justify-end sm:col-span-2">
              <Button type="submit" disabled={busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Save & test
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </motion.div>
  )
}

/* ------------------------------- Card ------------------------------- */

function LlmCard({
  conn,
  onChanged,
  onEdit,
  autoTest = false,
}: {
  conn: LlmConnection
  onChanged: () => void
  onEdit: () => void
  autoTest?: boolean
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [test, setTest] = useState<TestResult | null>(null)
  const [error, setError] = useState('')
  const badge = BADGES[conn.provider] || BADGES.custom

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
    const res = await run('test', () => api.post<TestResult>(`/api/llm/${conn.id}/test`))
    if (res) setTest(res)
    onChanged()
  }

  async function onDelete() {
    if (!window.confirm(`Delete "${conn.label}"?`)) return
    await run('delete', () => api.del(`/api/llm/${conn.id}`))
    onChanged()
  }

  const autoDone = useRef(false)
  useEffect(() => {
    if (autoTest && !autoDone.current) {
      autoDone.current = true
      void onTest()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTest, conn.id])

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="h-full">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${badge.cls} text-sm font-bold text-white`}
              >
                {badge.text}
              </div>
              <div className="min-w-0">
                <p className="truncate font-display text-sm font-semibold leading-tight">
                  {conn.label}
                </p>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {conn.provider_label} · {conn.api_key_masked || '—'}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 space-y-1.5 text-xs text-slate-500 dark:text-slate-400">
            {conn.base_url && (
              <p className="truncate">Base URL: {conn.base_url}</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <span>Model:</span>
              <span className="min-w-0 break-all font-mono text-xs font-medium text-slate-700 dark:text-slate-200">
                {conn.model || '—'}
              </span>
            </div>
          </div>

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
          {error && <p className="mt-3 break-words text-xs text-red-600 dark:text-red-400">{error}</p>}

          <div className="mt-4 flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onTest} disabled={busy !== null}>
              {busy === 'test' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Test
            </Button>
            <Button size="sm" variant="outline" onClick={onEdit} disabled={busy !== null}>
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </Button>
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
        </CardContent>
      </Card>
    </motion.div>
  )
}

/* ------------------------------- Page ------------------------------- */

export default function LlmPage() {
  const [config, setConfig] = useState<LlmConfig | null>(null)
  const [list, setList] = useState<LlmConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<LlmConnection | null>(null)
  const [error, setError] = useState('')
  const [autoTestId, setAutoTestId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [cfg, rows] = await Promise.all([
        api.get<LlmConfig>('/api/llm/config'),
        api.get<LlmConnection[]>('/api/llm'),
      ])
      setConfig(cfg)
      setList(rows)
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
          className="mb-8 flex flex-wrap items-end justify-between gap-4"
        >
          <div>
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-brand text-white shadow-lg shadow-brand-500/20">
              <Bot className="h-6 w-6" />
            </div>
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
              LLM Connections
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              Connect OpenAI, Claude, Gemini, Groq, OpenRouter or any OpenAI-compatible
              gateway. Keys are encrypted at rest; pick the model to use later for
              insights and assistants.
            </p>
          </div>
          <Button onClick={() => { setAdding((v) => !v); setEditing(null) }}>
            <Plus className="h-4 w-4" />
            Add LLM
          </Button>
        </motion.div>

        {error && (
          <p className="mb-4 rounded-xl bg-red-500/10 px-4 py-2.5 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        {config && (adding || editing) && (
          <LlmForm
            config={config}
            initial={editing}
            onSaved={(id) => {
              setAutoTestId(id)
              void refresh()
            }}
            onClose={() => {
              setAdding(false)
              setEditing(null)
            }}
          />
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        ) : list.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 p-12 text-center">
              <Bot className="h-6 w-6 text-slate-400" />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No LLM connections yet. Add your first provider above.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {list.map((c) => (
              <LlmCard
                key={c.id}
                conn={c}
                onChanged={refresh}
                onEdit={() => {
                  setEditing(c)
                  setAdding(false)
                }}
                autoTest={c.id === autoTestId}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
