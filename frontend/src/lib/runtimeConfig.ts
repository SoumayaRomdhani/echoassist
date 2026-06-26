import { env } from './env'

/**
 * Process-wide runtime configuration for the non-React data layer (api/ws).
 *
 * Defaults come from Vite env (standalone / demo host). When EchoAssist is
 * embedded in ACTEEK, `<EchoAssistAgent config={...}>` calls `configureRuntime`
 * once so REST + WebSocket talk to ACTEEK's API with ACTEEK's auth token —
 * without threading config through every hook.
 */
export interface RuntimeConfig {
  apiBaseUrl: string
  wsBaseUrl: string | null
  useMocks: boolean
  getAuthToken: () => string | null | Promise<string | null>
}

let current: RuntimeConfig = {
  apiBaseUrl: env.apiBaseUrl,
  wsBaseUrl: null,
  useMocks: env.useMocks,
  getAuthToken: () => null,
}

export function configureRuntime(partial: Partial<RuntimeConfig>): void {
  current = { ...current, ...partial }
}

export function getRuntime(): RuntimeConfig {
  return current
}

/** Base URL for WebSocket connections (explicit override, else derived from the API base). */
export function wsBaseUrl(): string {
  const base = current.wsBaseUrl ?? current.apiBaseUrl
  return base.replace(/^http/, 'ws')
}
