export type SsoProvider = 'microsoft' | 'google' | 'github'

export interface AuthUser {
  name: string
  email: string
  provider: SsoProvider | 'password'
}

export interface AuthSession {
  user: AuthUser
  /** Bearer token sent to the backend (REST + WS). In prod this is ACTEEK's SSO token. */
  token: string
}

export const SSO_LABELS: Record<SsoProvider, string> = {
  microsoft: 'Microsoft',
  google: 'Google',
  github: 'GitHub',
}

/**
 * Dev SSO stub. ARCHITECTURE.md §2 — *do not rebuild ACTEEK auth*. This fabricates
 * a local session so the standalone app has a real login flow for the demo. In
 * production ACTEEK's identity provider replaces these functions; the rest of the
 * app only consumes the returned {@link AuthSession} (and its `token`).
 */
function devToken(email: string): string {
  // Looks token-ish; the mock backend ignores it. Real tokens come from ACTEEK SSO.
  return `dev.${btoa(email)}.${Date.now().toString(36)}`
}

export async function signInWithSso(provider: SsoProvider): Promise<AuthSession> {
  // TODO(acteek-sso): redirect to ACTEEK's IdP and exchange the returned code/token.
  await delay(350)
  const email = 'mvp@acteek.com'
  return { user: { name: `${SSO_LABELS[provider]} User`, email, provider }, token: devToken(email) }
}

export async function signInWithPassword(email: string): Promise<AuthSession> {
  // TODO(acteek-sso): POST credentials to ACTEEK's auth endpoint.
  await delay(350)
  const handle = email.split('@')[0]
  const name = handle && handle.length > 0 ? handle : 'MVP'
  return { user: { name, email, provider: 'password' }, token: devToken(email) }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
