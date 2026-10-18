import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle,
  Bell,
  Bot,
  Check,
  ChevronRight,
  FileText,
  Loader2,
  Plus,
  ScrollText,
  Send,
  Settings2,
  ShieldAlert,
  Trash2,
  Wallet,
  X,
} from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import {
  api,
  type AgentRules,
  type AgentSettingsInfo,
  type AgentStatus,
  type AuditRow,
  type ChatMsg,
  type ConversationRow,
  type JobRow,
  type MemoryGraph,
  type MemoryNote,
  type NotifRow,
  type ProposalRow,
  type SignalRow,
  type TradeRow,
  type WatchItem,
} from '@/lib/api'

const TABS = [
  { id: 'chat', label: 'Chat', icon: Bot },
  { id: 'memory', label: 'Memory', icon: FileText },
  { id: 'rules', label: 'Rules', icon: ShieldAlert },
  { id: 'trades', label: 'Trades', icon: Wallet },
  { id: 'audit', label: 'Audit', icon: ScrollText },
  { id: 'notifs', label: 'Alerts', icon: Bell },
  { id: 'settings', label: 'Settings', icon: Settings2 },
] as const

type TabId = (typeof TABS)[number]['id']

function ModeBadge({ mode }: { mode: string }) {
  return (
    <span
      className={
        'rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ' +
        (mode === 'live'
          ? 'bg-red-500/15 text-red-600 dark:text-red-400'
          : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400')
      }
    >
      {mode}
    </span>
  )
}

/* ============================== CHAT ============================== */

type StreamEv =
  | { type: 'meta'; conversation_id: string; model: string; provider: string }
  | { type: 'text'; text: string }
  | { type: 'tool'; name: string; brief: string }
  | { type: 'confirm'; token: string; summary: string; tool: string }
  | { type: 'done'; message_id: number; title: string }
  | { type: 'error'; message: string }

function ConfirmCard({ token, summary, onDone }: { token: string; summary: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<string>('')
  async function act(kind: 'ok' | 'no') {
    setBusy(kind)
    try {
      if (kind === 'ok') {
        const res = await api.post<{ status?: string; detail?: string; error?: string }>('/api/agent/confirm', { token })
        setResult(res.error ? `✗ ${res.error}` : `✓ ${res.status || res.detail || 'done'}`)
      } else {
        setResult('✗ rejected')
      }
    } catch (e) {
      setResult(`✗ ${e instanceof Error ? e.message : 'failed'}`)
    } finally {
      setBusy(null)
      onDone()
    }
  }
  return (
    <div className="mt-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <p className="mb-1 font-medium text-amber-700 dark:text-amber-400">Confirm change</p>
      <p className="mb-2 whitespace-pre-wrap break-words text-xs">{summary}</p>
      {result ? (
        <p className="text-xs">{result}</p>
      ) : (
        <div className="flex gap-2">
          <Button size="sm" onClick={() => act('ok')} disabled={busy !== null}>
            {busy === 'ok' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            Confirm
          </Button>
          <Button size="sm" variant="outline" onClick={() => act('no')} disabled={busy !== null}>
            <X className="h-3.5 w-3.5" /> Reject
          </Button>
        </div>
      )}
    </div>
  )
}

function ChatView() {
  const [convs, setConvs] = useState<ConversationRow[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveText, setLiveText] = useState('')
  const [tools, setTools] = useState<string[]>([])
  const [confirms, setConfirms] = useState<{ token: string; summary: string }[]>([])
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const refreshConvs = useCallback(async () => {
    setConvs(await api.get<ConversationRow[]>('/api/agent/conversations'))
  }, [])

  const loadMsgs = useCallback(async (id: string) => {
    setMsgs(await api.get<ChatMsg[]>(`/api/agent/conversations/${id}/messages`))
  }, [])

  useEffect(() => {
    void refreshConvs()
  }, [refreshConvs])
  useEffect(() => {
    if (activeId) void loadMsgs(activeId)
  }, [activeId, loadMsgs])
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, liveText])

  async function send(e: React.FormEvent) {
    e.preventDefault()
    const content = input.trim()
    if (!content || streaming) return
    setInput('')
    setError('')
    setConfirms([])
    setTools([])
    setLiveText('')
    setStreaming(true)
    setMsgs((m) => [...m, { id: -Date.now(), role: 'user', content, tool_json: [], created_at: new Date().toISOString() }])
    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ conversation_id: activeId, content }),
      })
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}))
        throw new Error(j.detail || `HTTP ${resp.status}`)
      }
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let convId = activeId
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() || ''
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const ev = JSON.parse(line.slice(5)) as StreamEv
          if (ev.type === 'meta') {
            convId = ev.conversation_id
            setActiveId(ev.conversation_id)
          } else if (ev.type === 'text') {
            setLiveText((t) => t + ev.text)
          } else if (ev.type === 'tool') {
            setTools((t) => [...t, ev.name])
          } else if (ev.type === 'confirm') {
            setConfirms((c) => [...c, { token: ev.token, summary: ev.summary }])
          } else if (ev.type === 'error') {
            setError(ev.message)
          } else if (ev.type === 'done') {
            if (convId) await loadMsgs(convId)
            await refreshConvs()
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed')
    } finally {
      setStreaming(false)
      setLiveText('')
    }
  }

  return (
    <div className="grid h-[calc(100dvh-220px)] min-h-[420px] grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
      <Card className="hidden overflow-hidden lg:block">
        <CardContent className="flex h-full flex-col p-3">
          <Button size="sm" className="mb-2 w-full" onClick={async () => {
            const c = await api.post<{ id: string }>('/api/agent/conversations', {})
            setActiveId(c.id)
            setMsgs([])
            await refreshConvs()
          }}>
            <Plus className="h-4 w-4" /> New chat
          </Button>
          <div className="flex-1 space-y-1 overflow-y-auto">
            {convs.map((c) => (
              <button
                key={c.id}
                onClick={() => setActiveId(c.id)}
                className={
                  'block w-full truncate rounded-lg px-2.5 py-2 text-left text-xs ' +
                  (c.id === activeId
                    ? 'bg-brand-500/15 font-semibold text-brand-700 dark:text-brand-300'
                    : 'hover:bg-slate-100 dark:hover:bg-slate-800')
                }
              >
                {c.title}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="flex flex-col overflow-hidden">
        <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {msgs.length === 0 && !liveText && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-slate-500">
                <Bot className="h-8 w-8" />
                <p>Ask Igris about markets, propose a trade, or edit your rules.</p>
                <p className="text-xs">“What's my mode and open positions?” · “Add RELIANCE to watchlist”</p>
              </div>
            )}
            {msgs.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-sm text-white whitespace-pre-wrap break-words">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={m.id} className="max-w-[92%] space-y-2">
                  {m.tool_json?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {m.tool_json.map((t, i) => (
                        <span key={i} className="rounded-full bg-slate-200 px-2 py-0.5 font-mono text-[10px] dark:bg-slate-800">
                          {t.name}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="prose-chat text-sm leading-relaxed">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  </div>
                </div>
              ),
            )}
            {liveText && (
              <div className="max-w-[92%] space-y-2">
                {tools.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {tools.map((t, i) => (
                      <span key={i} className="rounded-full bg-brand-500/15 px-2 py-0.5 font-mono text-[10px] text-brand-700 dark:text-brand-300">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="prose-chat text-sm leading-relaxed">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{liveText}</ReactMarkdown>
                </div>
              </div>
            )}
            {confirms.map((c) => (
              <ConfirmCard key={c.token} token={c.token} summary={c.summary} onDone={() => {}} />
            ))}
            {streaming && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
            {error && (
              <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-400">{error}</p>
            )}
            <div ref={bottomRef} />
          </div>
          <form onSubmit={send} className="flex gap-2 border-t p-3">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Message Igris…"
              disabled={streaming}
            />
            <Button type="submit" disabled={streaming || !input.trim()}>
              {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

/* ============================== MEMORY ============================== */

function MemoryView() {
  const [tab, setTab] = useState<'notes' | 'watchlist' | 'signals' | 'graph'>('notes')
  const [notes, setNotes] = useState<MemoryNote[]>([])
  const [watch, setWatch] = useState<WatchItem[]>([])
  const [signals, setSignals] = useState<SignalRow[]>([])
  const [graph, setGraph] = useState<MemoryGraph | null>(null)
  const [newWatch, setNewWatch] = useState('')
  const [noteForm, setNoteForm] = useState({ title: '', body: '', entities: '' })
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const [n, w, s, g] = await Promise.all([
      api.get<MemoryNote[]>('/api/agent/memory/notes'),
      api.get<WatchItem[]>('/api/agent/memory/watchlist'),
      api.get<SignalRow[]>('/api/agent/memory/signals'),
      api.get<MemoryGraph>('/api/agent/memory/graph'),
    ])
    setNotes(n); setWatch(w); setSignals(s); setGraph(g)
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const neighbors = useMemo(() => {
    if (!graph || !selected) return []
    const out: { label: string; rel: string }[] = []
    for (const e of graph.edges) {
      if (e.from === `note:${selected}` || e.from === selected) {
        const id = e.to.split(':')[1] ?? e.to
        const node = graph.nodes.find((n) => n.id === id)
        out.push({ label: node?.label ?? id, rel: e.rel })
      }
      if (e.to === `note:${selected}` || e.to === selected) {
        const id = e.from.split(':')[1] ?? e.from
        const node = graph.nodes.find((n) => n.id === id)
        out.push({ label: node?.label ?? id, rel: e.rel })
      }
    }
    return out
  }, [graph, selected])

  async function addWatch(e: React.FormEvent) {
    e.preventDefault()
    if (!newWatch.trim()) return
    setBusy(true)
    await api.post('/api/agent/memory/watchlist', { symbol: newWatch.trim() })
    setNewWatch('')
    await refresh()
    setBusy(false)
  }
  async function saveNote(e: React.FormEvent) {
    e.preventDefault()
    if (!noteForm.title.trim()) return
    setBusy(true)
    await api.post('/api/agent/memory/notes', {
      title: noteForm.title,
      body: noteForm.body,
      entities: noteForm.entities.split(',').map((s) => s.trim()).filter(Boolean),
    })
    setNoteForm({ title: '', body: '', entities: '' })
    await refresh()
    setBusy(false)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {(['notes', 'watchlist', 'signals', 'graph'] as const).map((t) => (
          <Button key={t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </Button>
        ))}
      </div>

      {tab === 'notes' && (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <div className="space-y-3">
            {notes.map((n) => (
              <Card key={n.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-display text-sm font-semibold">{n.title}</p>
                    <button onClick={async () => { await api.del(`/api/agent/memory/notes/${n.id}`); void refresh() }} className="text-slate-400 hover:text-red-500">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-xs text-slate-600 dark:text-slate-300">{n.body.slice(0, 400)}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {n.entities.map((e) => (
                      <span key={e} className="rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-700 dark:text-brand-300">{e}</span>
                    ))}
                    <span className="ml-auto text-[10px] text-slate-400">by {n.created_by}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
            {notes.length === 0 && <p className="text-sm text-slate-500">No notes yet — ask Igris to write one.</p>}
          </div>
          <Card className="h-fit">
            <CardContent className="p-4">
              <p className="mb-3 font-display text-sm font-semibold">New note</p>
              <form onSubmit={saveNote} className="space-y-3">
                <Input value={noteForm.title} onChange={(e) => setNoteForm({ ...noteForm, title: e.target.value })} placeholder="Title" required />
                <textarea
                  className="min-h-[80px] w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                  value={noteForm.body}
                  onChange={(e) => setNoteForm({ ...noteForm, body: e.target.value })}
                  placeholder="Body"
                />
                <Input value={noteForm.entities} onChange={(e) => setNoteForm({ ...noteForm, entities: e.target.value })} placeholder="Entities: RELIANCE, BANKNIFTY" />
                <Button type="submit" size="sm" disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Save</Button>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {tab === 'watchlist' && (
        <div className="max-w-xl space-y-3">
          <form onSubmit={addWatch} className="flex gap-2">
            <Input value={newWatch} onChange={(e) => setNewWatch(e.target.value)} placeholder="Symbol (e.g. RELIANCE)" />
            <Button disabled={busy}><Plus className="h-4 w-4" /> Add</Button>
          </form>
          {watch.map((w) => (
            <div key={w.id} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
              <div>
                <p className="text-sm font-semibold">{w.symbol}</p>
                {w.notes && <p className="text-xs text-slate-500">{w.notes}</p>}
              </div>
              <button onClick={async () => { await api.del(`/api/agent/memory/watchlist/${w.id}`); void refresh() }} className="text-slate-400 hover:text-red-500">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {watch.length === 0 && <p className="text-sm text-slate-500">Watchlist empty.</p>}
        </div>
      )}

      {tab === 'signals' && (
        <div className="space-y-2">
          {signals.map((s) => (
            <div key={s.id} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
              <span className={'text-xs font-bold ' + (s.direction === 'long' ? 'text-emerald-600' : 'text-red-500')}>{s.direction.toUpperCase()}</span>
              <span className="text-sm font-semibold">{s.symbol}</span>
              <span className="truncate text-xs text-slate-500">{s.catalyst}</span>
              <span className="ml-auto text-xs text-slate-400">{s.score.toFixed(2)}</span>
            </div>
          ))}
          {signals.length === 0 && <p className="text-sm text-slate-500">No signals yet.</p>}
        </div>
      )}

      {tab === 'graph' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="p-4">
              <p className="mb-2 font-display text-sm font-semibold">Memory graph (linked notes)</p>
              <div className="space-y-1">
                {(graph?.nodes ?? []).map((n) => (
                  <button
                    key={n.kind + n.id}
                    onClick={() => setSelected(n.id)}
                    className={
                      'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs ' +
                      (selected === n.id ? 'bg-brand-500/15 font-semibold' : 'hover:bg-slate-100 dark:hover:bg-slate-800')
                    }
                  >
                    <span className={'rounded px-1.5 py-0.5 text-[9px] font-bold ' + (n.kind === 'note' ? 'bg-sky-500/15 text-sky-600' : 'bg-emerald-500/15 text-emerald-600')}>
                      {n.kind}
                    </span>
                    <span className="truncate">{n.label}</span>
                  </button>
                ))}
                {(graph?.nodes.length ?? 0) === 0 && <p className="text-sm text-slate-500">Empty — write notes with entities to build the graph.</p>}
              </div>
            </CardContent>
          </Card>
          <Card className="h-fit">
            <CardContent className="p-4">
              <p className="mb-2 font-display text-sm font-semibold">Neighbors{selected ? ` · ${graph?.nodes.find((n) => n.id === selected)?.label}` : ''}</p>
              {neighbors.length === 0 ? (
                <p className="text-sm text-slate-500">Select a node to see linked entities/notes.</p>
              ) : (
                <ul className="space-y-1.5">
                  {neighbors.map((nb, i) => (
                    <li key={i} className="flex items-center gap-2 text-sm">
                      <ChevronRight className="h-3 w-3 text-slate-400" />
                      <span>{nb.label}</span>
                      <span className="text-[10px] text-slate-400">{nb.rel}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

/* ============================== RULES ============================== */

function RulesView({ onChanged }: { onChanged: () => void }) {
  const [rules, setRules] = useState<AgentRules | null>(null)
  const [liveConfirm, setLiveConfirm] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => setRules(await api.get<AgentRules>('/api/agent/rules')), [])
  useEffect(() => { void load() }, [load])

  async function patch(changes: Partial<AgentRules>) {
    setBusy(true); setMsg('')
    try {
      const res = await api.patch<{ detail: string }>('/api/agent/rules', changes)
      setMsg(res.detail)
      await load(); onChanged()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'failed')
    } finally { setBusy(false) }
  }

  async function setMode(mode: 'paper' | 'live') {
    setBusy(true); setMsg('')
    try {
      const res = await api.post<{ detail: string }>('/api/agent/mode', { mode, confirm: liveConfirm })
      setMsg(res.detail); setLiveConfirm('')
      await load(); onChanged()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'failed')
    } finally { setBusy(false) }
  }

  if (!rules) return <Loader2 className="h-5 w-5 animate-spin" />

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardContent className="space-y-4 p-5">
          <p className="font-display text-sm font-semibold">Risk rules</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Capital (₹)</Label>
              <Input type="number" defaultValue={rules.capital} onBlur={(e) => patch({ capital: +e.target.value })} /></div>
            <div className="space-y-1"><Label>Risk / trade %</Label>
              <Input type="number" step="0.1" defaultValue={rules.risk_per_trade_pct} onBlur={(e) => patch({ risk_per_trade_pct: +e.target.value })} /></div>
            <div className="space-y-1"><Label>Max open positions</Label>
              <Input type="number" defaultValue={rules.max_open_positions} onBlur={(e) => patch({ max_open_positions: +e.target.value })} /></div>
            <div className="space-y-1"><Label>Daily loss limit %</Label>
              <Input type="number" step="0.1" defaultValue={rules.daily_loss_limit_pct} onBlur={(e) => patch({ daily_loss_limit_pct: +e.target.value })} /></div>
            <div className="space-y-1"><Label>Max daily trades</Label>
              <Input type="number" defaultValue={rules.max_daily_trades} onBlur={(e) => patch({ max_daily_trades: +e.target.value })} /></div>
            <div className="space-y-1"><Label>Strategy ID</Label>
              <Input defaultValue={rules.strategy_id} onBlur={(e) => patch({ strategy_id: e.target.value })} /></div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={rules.notify_on_long} onChange={(e) => patch({ notify_on_long: e.target.checked })} />
            Notify me when a LONG trade is opened
          </label>
          <p className="text-[11px] text-slate-400">
            Hard caps (code): risk ≤ {String((rules.hard_caps as Record<string, unknown>)?.max_risk_per_trade_pct ?? 2)}% ·
            positions ≤ {String((rules.hard_caps as Record<string, unknown>)?.max_open_positions ?? 5)} ·
            loss ≤ {String((rules.hard_caps as Record<string, unknown>)?.max_daily_loss_limit_pct ?? 3)}%
          </p>
          {msg && <p className="text-xs text-slate-500">{msg}</p>}
        </CardContent>
      </Card>

      <Card className={rules.mode === 'live' ? 'border-red-500/50' : ''}>
        <CardContent className="space-y-4 p-5">
          <p className="font-display text-sm font-semibold">Trading mode</p>
          <div className="flex items-center gap-3">
            <ModeBadge mode={rules.mode} />
            <span className="text-sm text-slate-500">autonomy: {rules.autonomy}</span>
            {rules.kill_switch && <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-bold text-red-600">KILL SWITCH</span>}
          </div>
          {rules.mode === 'paper' ? (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">Paper mode: all trades simulated with realistic costs. No broker orders.</p>
              <div className="flex flex-wrap items-center gap-2">
                <Input value={liveConfirm} onChange={(e) => setLiveConfirm(e.target.value)} placeholder='Type "LIVE" to enable' className="max-w-[220px]" />
                <Button variant="destructive" disabled={busy || liveConfirm.trim().toUpperCase() !== 'LIVE'} onClick={() => setMode('live')}>
                  Go live
                </Button>
              </div>
              <p className="text-[11px] text-amber-600">Live sends real orders via your broker from the whitelisted IP. Per-trade approval is on by default.</p>
            </div>
          ) : (
            <div className="space-y-2">
              <Select value={rules.autonomy} onChange={(e) => patch({ autonomy: e.target.value as AgentRules['autonomy'] })}>
                <option value="live_approve">Approve each trade (recommended)</option>
                <option value="live_auto">Autonomous (Risk Manager gates every order)</option>
              </Select>
              <Button variant="outline" disabled={busy} onClick={() => setMode('paper')}>Back to paper</Button>
            </div>
          )}
          <hr className="border-slate-200 dark:border-slate-800" />
          {rules.kill_switch ? (
            <Button variant="outline" disabled={busy} onClick={async () => { await api.post('/api/agent/kill/reset'); await load(); onChanged() }}>
              Clear kill switch
            </Button>
          ) : (
            <Button variant="destructive" disabled={busy} onClick={async () => { await api.post('/api/agent/kill'); await load(); onChanged() }}>
              <AlertTriangle className="h-4 w-4" /> Kill switch — halt all trading
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ============================== TRADES ============================== */

function TradesView() {
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [props, setProps] = useState<ProposalRow[]>([])
  const [status, setStatus] = useState<AgentStatus | null>(null)

  const refresh = useCallback(async () => {
    const [t, p, s] = await Promise.all([
      api.get<TradeRow[]>('/api/agent/trades'),
      api.get<ProposalRow[]>('/api/agent/proposals'),
      api.get<AgentStatus>('/api/agent/status'),
    ])
    setTrades(t); setProps(p); setStatus(s)
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Mode', value: status?.mode ?? '—' },
          { label: 'Open', value: status?.open_positions ?? 0 },
          { label: 'Today P&L', value: status ? `₹${status.today_realised_pnl.toFixed(0)}` : '—' },
          { label: 'Market', value: status?.market_open ? 'OPEN' : 'CLOSED' },
        ].map((c) => (
          <Card key={c.label}><CardContent className="p-4">
            <p className="text-[11px] uppercase tracking-wide text-slate-400">{c.label}</p>
            <p className="font-display text-lg font-bold">{c.value}</p>
          </CardContent></Card>
        ))}
      </div>

      <div>
        <p className="mb-2 font-display text-sm font-semibold">Trades</p>
        <div className="space-y-2">
          {trades.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
              <ModeBadge mode={t.mode} />
              <span className={'text-xs font-bold ' + (t.is_long ? 'text-emerald-600' : 'text-red-500')}>{t.side}</span>
              <span className="text-sm font-semibold">{t.symbol}</span>
              <span className="text-xs text-slate-500">{t.instrument}{t.expiry ? ` · ${t.expiry}` : ''}</span>
              <span className="text-xs text-slate-400">{t.qty} @ {t.entry_px}{t.exit_px ? ` → ${t.exit_px}` : ''}</span>
              <span className={'text-xs font-semibold ' + ((t.pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500')}>
                {t.status === 'closed' && t.pnl !== null ? `₹${t.pnl.toFixed(0)}` : t.status}
                {t.status === 'closed' && t.exit_reason ? ` · ${t.exit_reason}` : ''}
              </span>
              {t.status === 'pending_approval' && (
                <Button size="sm" className="ml-auto" onClick={async () => { await api.post(`/api/agent/trades/${t.id}/approve`); void refresh() }}>
                  <Check className="h-3.5 w-3.5" /> Approve order
                </Button>
              )}
              {t.status === 'open' && t.mode === 'paper' && (
                <Button size="sm" variant="outline" className="ml-auto" onClick={async () => { await api.post(`/api/agent/trades/${t.id}/close`); void refresh() }}>
                  Close
                </Button>
              )}
            </div>
          ))}
          {trades.length === 0 && <p className="text-sm text-slate-500">No trades yet.</p>}
        </div>
      </div>

      <div>
        <p className="mb-2 font-display text-sm font-semibold">Proposals (risk-checked)</p>
        <div className="space-y-2">
          {props.map((p) => (
            <div key={p.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs dark:border-slate-800 dark:bg-slate-900">
              <div className="flex flex-wrap items-center gap-2">
                <ModeBadge mode={p.mode} />
                <span className="font-semibold">{p.symbol}</span>
                <span>{p.side} {p.instrument}</span>
                <span className="text-slate-400">E {p.entry} / S {p.stop} / T {p.target}</span>
                <span className={'ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold ' +
                  (p.status === 'vetoed' ? 'bg-red-500/15 text-red-600' : p.status === 'filled' ? 'bg-emerald-500/15 text-emerald-600' : 'bg-slate-500/15 text-slate-500')}>
                  {p.status}
                </span>
              </div>
              {p.rationale && <p className="mt-1 text-slate-500">{p.rationale}</p>}
              {p.veto_reason && <p className="mt-1 text-red-500">Veto: {p.veto_reason}</p>}
            </div>
          ))}
          {props.length === 0 && <p className="text-sm text-slate-500">No proposals yet.</p>}
        </div>
      </div>
    </div>
  )
}

/* ===================== AUDIT / ALERTS / SETTINGS ===================== */

function AuditView() {
  const [rows, setRows] = useState<AuditRow[]>([])
  useEffect(() => { void api.get<AuditRow[]>('/api/agent/audit').then(setRows) }, [])
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-900">
          <span className="font-mono text-[10px] text-slate-400">{new Date(r.created_at).toLocaleString()}</span>
          <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] dark:bg-slate-800">{r.actor}</span>
          <span className="ml-2 font-semibold">{r.action}</span>
          <p className="mt-0.5 break-words text-slate-500">{r.detail.slice(0, 300)}</p>
        </div>
      ))}
      {rows.length === 0 && <p className="text-sm text-slate-500">Audit log empty.</p>}
    </div>
  )
}

function NotifsView() {
  const [rows, setRows] = useState<NotifRow[]>([])
  const refresh = useCallback(async () => setRows(await api.get<NotifRow[]>('/api/agent/notifications')), [])
  useEffect(() => { void refresh() }, [refresh])
  return (
    <div className="space-y-2">
      <Button size="sm" variant="outline" onClick={async () => { await api.post('/api/agent/notifications/read'); void refresh() }}>
        Mark all read
      </Button>
      {rows.map((r) => (
        <div key={r.id} className={'rounded-lg border px-3 py-2 text-sm ' + (r.read ? 'border-slate-200 opacity-60 dark:border-slate-800' : 'border-brand-500/40 bg-brand-500/5')}>
          <div className="flex items-center gap-2">
            {!r.read && <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />}
            <span className="font-semibold">{r.title}</span>
            <span className="ml-auto text-[10px] text-slate-400">{new Date(r.created_at).toLocaleString()}</span>
          </div>
          {r.body && <p className="mt-0.5 text-xs text-slate-500">{r.body}</p>}
        </div>
      ))}
      {rows.length === 0 && <p className="text-sm text-slate-500">No alerts.</p>}
    </div>
  )
}

function SettingsView() {
  const [settings, setSettings] = useState<AgentSettingsInfo | null>(null)
  const [jobs, setJobs] = useState<JobRow[]>([])
  const [jobForm, setJobForm] = useState({ name: '', tool_name: 'research_symbol', symbol: '', interval_minutes: 30 })
  const [msg, setMsg] = useState('')

  const refresh = useCallback(async () => {
    const [s, j] = await Promise.all([
      api.get<AgentSettingsInfo>('/api/agent/settings'),
      api.get<JobRow[]>('/api/agent/jobs'),
    ])
    setSettings(s); setJobs(j)
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  async function addJob(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    try {
      await api.post('/api/agent/jobs', {
        name: jobForm.name || jobForm.tool_name,
        tool_name: jobForm.tool_name,
        args: jobForm.symbol ? { symbol: jobForm.symbol.toUpperCase() } : {},
        interval_minutes: jobForm.interval_minutes,
      })
      setJobForm({ name: '', tool_name: 'research_symbol', symbol: '', interval_minutes: 30 })
      await refresh()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'failed')
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardContent className="space-y-3 p-5">
          <p className="font-display text-sm font-semibold">Agent model</p>
          <Select
            value={settings?.llm_connection_id || ''}
            onChange={async (e) => { await api.patch('/api/agent/settings', { llm_connection_id: e.target.value }); void refresh() }}
          >
            <option value="">Auto (first LLM connection)</option>
            {(settings?.llm_options ?? []).map((o) => (
              <option key={o.id} value={o.id}>{o.label} · {o.provider} · {o.model}</option>
            ))}
          </Select>
          <p className="text-[11px] text-slate-400">Add or edit connections on the LLM tab.</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-3 p-5">
          <p className="font-display text-sm font-semibold">Scheduled jobs</p>
          <form onSubmit={addJob} className="grid grid-cols-2 gap-2">
            <Input value={jobForm.name} onChange={(e) => setJobForm({ ...jobForm, name: e.target.value })} placeholder="Name" />
            <Select value={jobForm.tool_name} onChange={(e) => setJobForm({ ...jobForm, tool_name: e.target.value })}>
              <option value="research_symbol">research_symbol</option>
              <option value="get_quote">get_quote</option>
              <option value="get_system_status">get_system_status</option>
            </Select>
            <Input value={jobForm.symbol} onChange={(e) => setJobForm({ ...jobForm, symbol: e.target.value })} placeholder="Symbol (optional)" />
            <Input type="number" min={5} value={jobForm.interval_minutes} onChange={(e) => setJobForm({ ...jobForm, interval_minutes: +e.target.value })} />
            <Button size="sm" className="col-span-2"><Plus className="h-3.5 w-3.5" /> Schedule</Button>
          </form>
          {msg && <p className="text-xs text-red-500">{msg}</p>}
          {jobs.map((j) => (
            <div key={j.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
              <span className="font-semibold">{j.name}</span>
              <span className="text-slate-400">{j.tool_name} /{j.interval_minutes}m</span>
              {j.last_result && <span className="truncate text-slate-400">{j.last_result.slice(0, 60)}</span>}
              <button className="ml-auto text-slate-400 hover:text-red-500" onClick={async () => { await api.del(`/api/agent/jobs/${j.id}`); void refresh() }}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

/* ============================== PAGE ============================== */

export default function IgrisPage() {
  const [tab, setTab] = useState<TabId>('chat')
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [unread, setUnread] = useState(0)

  const refreshStatus = useCallback(async () => {
    const s = await api.get<AgentStatus>('/api/agent/status').catch(() => null)
    setStatus(s)
  }, [])

  useEffect(() => {
    void refreshStatus()
    const t = setInterval(refreshStatus, 30000)
    return () => clearInterval(t)
  }, [refreshStatus])

  useEffect(() => {
    if (tab === 'notifs') {
      setUnread(0)
      return
    }
    void api.get<NotifRow[]>('/api/agent/notifications').then((rows) => {
      setUnread(rows.filter((r) => !r.read).length)
    }).catch(() => {})
  }, [tab])

  return (
    <div className="min-h-dvh bg-slate-50 dark:bg-slate-950">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-brand text-white shadow-lg shadow-brand-500/20">
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <h1 className="font-display text-2xl font-bold tracking-tight">Igris</h1>
                <p className="text-xs text-slate-500">AI trading agent · shared memory · paper-first</p>
              </div>
            </div>
            {status && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <ModeBadge mode={status.mode} />
                <span className={'rounded-full px-2 py-0.5 font-medium ' + (status.market_open ? 'bg-emerald-500/10 text-emerald-600' : 'bg-slate-500/10 text-slate-500')}>
                  {status.market_open ? 'Market open' : 'Market closed'}
                </span>
                {status.kill_switch && <span className="rounded-full bg-red-500/15 px-2 py-0.5 font-bold text-red-600">KILL</span>}
                <span className="text-slate-500">P&L today ₹{status.today_realised_pnl.toFixed(0)} · {status.open_positions} open</span>
              </div>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-1.5 border-b border-slate-200 pb-2 dark:border-slate-800">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ' +
                  (tab === t.id
                    ? 'bg-brand-600 text-white'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800')
                }
              >
                <t.icon className="h-3.5 w-3.5" />
                {t.label}
                {t.id === 'notifs' && unread > 0 && (
                  <span className="rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">{unread}</span>
                )}
              </button>
            ))}
          </div>
        </motion.div>

        {tab === 'chat' && <ChatView />}
        {tab === 'memory' && <MemoryView />}
        {tab === 'rules' && <RulesView onChanged={refreshStatus} />}
        {tab === 'trades' && <TradesView />}
        {tab === 'audit' && <AuditView />}
        {tab === 'notifs' && <NotifsView />}
        {tab === 'settings' && <SettingsView />}
      </main>
    </div>
  )
}
