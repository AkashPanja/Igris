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
