import { useMemo, useState } from 'react'
import { useAuth } from './auth/AuthProvider'
import { DomainSwitcher } from './components/DomainSwitcher'
import { HostShell } from './components/HostShell'
import { EchoAssistAgent } from './embed'
import type { AgentSection, EchoAssistConfig } from './embed'
import { LoginPage } from './features/auth/LoginPage'
import { env } from './lib/env'

/**
 * Standalone host (NOT shipped to ACTEEK): a login gate + a SaaS shell (dark sidebar
 * + top bar) around the embeddable `<EchoAssistAgent>`. The sidebar drives the agent's
 * active section; the signed-in session's token flows to the agent via `getAuthToken` —
 * exactly where ACTEEK's SSO token goes when they embed the agent in their own shell.
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
  const [section, setSection] = useState<AgentSection>('overview')
  const [query, setQuery] = useState('')
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
    <HostShell
      section={section}
      onSection={setSection}
      searchValue={query}
      onSearch={setQuery}
      domainSlot={<DomainSwitcher value={domain} onChange={setDomain} />}
    >
      <EchoAssistAgent
        config={config}
        section={section}
        onSection={setSection}
        query={query}
        renderToaster={false}
      />
    </HostShell>
  )
}
