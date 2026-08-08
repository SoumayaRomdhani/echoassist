/**
 * Integration contract for embedding EchoAssist into the ACTEEK marketplace.
 *
 * ACTEEK owns the shell, theme, and SSO; EchoAssist is mounted as a single
 * `<EchoAssistAgent config={...} />` component and consumes only this config.
 */
export interface EchoAssistConfig {
  /** Base URL of the EchoAssist backend (REST). Required. */
  apiBaseUrl: string
  /** Base URL for the WebSocket; derived from `apiBaseUrl` (http→ws) if omitted. */
  wsBaseUrl?: string
  /** Interview domain to operate on. Defaults to "screening". */
  domain?: string
  /**
   * Returns the ACTEEK SSO token to send as `Authorization: Bearer <token>`
   * (and as the `access_token` WS query param). May be async. The host owns auth.
   */
  getAuthToken?: () => string | null | Promise<string | null>
  /** Demo/offline only: serve from the in-browser mock backend. Defaults to false. */
  useMocks?: boolean
}

/** Top-level workspace sections, driven by the host shell's sidebar. */
export type AgentSection = 'overview' | 'calls' | 'interviews' | 'metrics' | 'config'

/** Config with defaults applied, provided to components via context. */
export interface ResolvedConfig {
  apiBaseUrl: string
  wsBaseUrl: string | null
  domain: string
  getAuthToken: () => string | null | Promise<string | null>
  useMocks: boolean
}

export function resolveConfig(config: EchoAssistConfig): ResolvedConfig {
  return {
    apiBaseUrl: config.apiBaseUrl.replace(/\/+$/, ''),
    wsBaseUrl: config.wsBaseUrl ? config.wsBaseUrl.replace(/\/+$/, '') : null,
    domain: config.domain ?? 'screening',
    getAuthToken: config.getAuthToken ?? (() => null),
    useMocks: config.useMocks ?? false,
  }
}
