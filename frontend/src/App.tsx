import { useMemo } from 'react'
import { useAuth } from './auth/AuthProvider'
import { AppFrame } from './components/AppFrame'
import { EchoAssistAgent } from './embed'
import type { EchoAssistConfig } from './embed'
import { LoginPage } from './features/auth/LoginPage'
import { env } from './lib/env'

/**
 * Standalone host (NOT shipped to ACTEEK): a login gate + a slim branded frame
 * around the embeddable `<EchoAssistAgent>`. The signed-in session's token is
 * handed to the agent via `getAuthToken` — exactly where ACTEEK's SSO token goes
 * when they embed the agent in their own marketplace.
 */
export default function App() {
  const { user } = useAuth()
  return user ? <AuthedApp /> : <LoginPage />
}

function AuthedApp() {
  const { token } = useAuth()
  const config = useMemo<EchoAssistConfig>(
    () => ({
      apiBaseUrl: env.apiBaseUrl,
      useMocks: env.useMocks,
      domain: 'screening',
      getAuthToken: () => token,
    }),
    [token],
  )

  return (
    <AppFrame>
      <EchoAssistAgent config={config} renderToaster={false} />
    </AppFrame>
  )
}
