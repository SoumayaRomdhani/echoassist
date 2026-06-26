import { ThemeToggle } from './components/ThemeToggle'
import { EchoAssistAgent } from './embed'
import type { EchoAssistConfig } from './embed'
import { env } from './lib/env'

/**
 * Standalone dev harness — NOT part of the deliverable.
 *
 * The deliverable is `<EchoAssistAgent>` (see src/embed). ACTEEK mounts it inside
 * their own marketplace shell with their API + SSO token. This wrapper only exists
 * so the agent can be run and presented on its own during development: it sets a
 * full-bleed background, a dev theme toggle, and feeds the agent a demo config
 * (mock backend in dev unless VITE_USE_MOCKS=false).
 */
const demoConfig: EchoAssistConfig = {
  apiBaseUrl: env.apiBaseUrl,
  useMocks: env.useMocks,
  domain: 'screening',
  getAuthToken: () => null,
}

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="fixed right-4 top-4 z-50">
        <ThemeToggle />
      </div>
      <EchoAssistAgent config={demoConfig} />
    </div>
  )
}
