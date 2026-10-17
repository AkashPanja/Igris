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

export type LlmProvider = 'openai' | 'anthropic' | 'gemini' | 'groq' | 'openrouter' | 'custom'

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
