import { useMemo, useState } from 'react'
import { useAuth } from './auth/AuthProvider'
import { AppFrame } from './components/AppFrame'
import { DomainSwitcher } from './components/DomainSwitcher'
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
  // The host owns the active domain so the whole dashboard can switch between the
  // deployment's agents (screening, helpdesk, …). The embed itself stays single-domain.
  const [domain, setDomain] = useState('screening')
  const config = useMemo<EchoAssistConfig>(
    () => ({
      apiBaseUrl: env.apiBaseUrl,
      useMocks: env.useMocks,
      domain,
      getAuthToken: () => token,
    }),
    [token, domain],
  )

  return (
    <AppFrame headerSlot={<DomainSwitcher value={domain} onChange={setDomain} />}>
      <EchoAssistAgent config={config} renderToaster={false} />
    </AppFrame>
  )
}
