export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export interface SetupState {
  installed: boolean
  setup_token_required: boolean
  smtp_configured: boolean
}

export interface UserOut {
  id: number
  username: string
  email: string
}

export interface SessionOut {
  user: UserOut
  csrf_token: string
}

export interface SmtpTestResult {
  success: boolean
  message: string
}

export interface SmtpConfig {
  host: string
  port: number
  security: 'None' | 'STARTTLS' | 'SSL'
  username: string
  password: string
  from_name: string
  from_email: string
}

export type Provider = 'fyers' | 'groww'
export type ConnectionStatus = 'never_authed' | 'connected' | 'needs_auth' | 'error'

export interface Connection {
  id: string
  provider: Provider
  label: string
  app_id: string
  status: ConnectionStatus
  expires_at: string | null
  reauth_time: string
  last_error: string
  last_reauth_at: string | null
  tools: string[]
}

export interface ConnectionsConfig {
  public_base_url: string
  manual_flow: boolean
  redirect_uri: string
  help: Record<
    string,
    { title: string; url: string; url_label: string; steps: string[] }
  >
  tools: Record<string, string[]>
}

export interface TestResult {
  success: boolean
  message: string
}

export type LlmProvider = 'openai' | 'anthropic' | 'gemini' | 'groq' | 'openrouter' | 'cloudflare' | 'custom'

export interface LlmConnection {
  id: string
  provider: LlmProvider
  provider_label: string
  label: string
  api_key_masked: string
  base_url: string
  model: string
  created_at: string | null
}

export interface LlmProviderInfo {
  id: LlmProvider
  label: string
  key_hint: string
  models: string[]
  base_url_required: boolean
  docs: string
}

export interface LlmConfig {
  providers: LlmProviderInfo[]
}

// ---------------- Igris agent (S4) ----------------

export interface AgentRules {
  capital: number
  risk_per_trade_pct: number
  max_open_positions: number
  daily_loss_limit_pct: number
  max_daily_trades: number
  mode: 'paper' | 'live'
  autonomy: 'paper' | 'live_approve' | 'live_auto'
  instruments_allowed: string[]
  strategy_id: string
  kill_switch: boolean
  notify_on_long: boolean
  hard_caps?: Record<string, unknown>
}

export interface TradeRow {
  id: string
  proposal_id: string
  symbol: string
  side: string
  instrument: string
  expiry: string
  strike: string
  mode: 'paper' | 'live'
  qty: number
  entry_px: number
  stop_px: number
  target_px: number
  exit_px: number | null
  slippage: number
  costs: number
  pnl: number | null
  status: string
  exit_reason: string
  broker_order_id: string
  is_long: boolean
  opened_at: string | null
  closed_at: string | null
}

export interface ProposalRow {
  id: string
  symbol: string
  side: string
  instrument: string
  expiry: string
  strike: string
  entry: number
  stop: number
  target: number
  qty: number
  rationale: string
  confidence: number
  source: string
  status: string
  veto_reason: string
  mode: string
  created_at: string | null
}

export interface MemoryNote {
  id: string
  title: string
  body: string
  sentiment: number | null
  entities: string[]
  sources: string[]
  pinned: boolean
  created_by: string
  created_at: string
}

export interface WatchItem {
  id: number
  symbol: string
  notes: string
  source: string
}

export interface SignalRow {
  id: number
  symbol: string
  direction: string
  catalyst: string
  score: number
  source: string
  created_by: string
}

export interface AuditRow {
  id: number
  actor: string
  action: string
  detail: string
  created_at: string
}

export interface NotifRow {
  id: number
  kind: string
  title: string
  body: string
  read: boolean
  created_at: string
}

export interface JobRow {
  id: string
  name: string
  tool_name: string
  args: Record<string, unknown>
  interval_minutes: number
  market_hours_only: boolean
  enabled: boolean
  last_run_at: string | null
  last_result: string
}

export interface ConversationRow {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMsg {
  id: number
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  tool_json: { name: string; args: Record<string, unknown>; result: Record<string, unknown> }[]
  created_at: string
}

export interface AgentSettingsInfo {
  llm_connection_id: string
  model: string
  llm_options: { id: string; label: string; provider: string; model: string }[]
}

export interface MemoryGraph {
  nodes: { id: string; kind: 'note' | 'entity'; label: string; pinned: boolean; entities: string[] }[]
  edges: { from: string; to: string; rel: string }[]
}

export interface AgentStatus {
  mode: string
  autonomy: string
  kill_switch: boolean
  market_open: boolean
  capital: number
  risk_per_trade_pct: number
  daily_loss_limit_pct: number
  max_open_positions: number
  open_positions: number
  open_trades: TradeRow[]
  today_realised_pnl: number
  broker_connections: { id: string; provider: string; status: string; label: string }[]
}

export interface ModelsResponse {
  models: string[]
  source: string
  provider: string
}
