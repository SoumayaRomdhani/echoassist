import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AgentDetailPage } from '@/features/agent/AgentDetailPage'
import { CallDetailPage } from '@/features/calls/CallDetailPage'
import { configureRuntime } from '@/lib/runtimeConfig'
import '@/styles/index.css'
import { AgentConfigProvider } from './AgentConfigContext'
import { resolveConfig, type EchoAssistConfig } from './types'

export interface EchoAssistAgentProps {
  config: EchoAssistConfig
  /** Render an internal toast host. Set false if the host page already mounts one. */
  renderToaster?: boolean
}

/**
 * The embeddable EchoAssist agent — the actual Sprint 7 deliverable.
 *
 * Self-contained: it brings its own data layer (TanStack Query) and tooltip host,
 * and drives list↔detail navigation with local state (no router — so it never
 * touches the host URL and works regardless of the host's routing stack).
 * ACTEEK mounts it inside their marketplace shell with one line:
 *
 *   <EchoAssistAgent config={{ apiBaseUrl, getAuthToken }} />
 *
 * It does NOT render the marketplace, sidebar, theme toggle, or login — those
 * belong to ACTEEK (ARCHITECTURE.md §2). Theme is inherited from the host's
 * `[data-theme]` via the shared `--c-*` tokens.
 */
export function EchoAssistAgent({ config, renderToaster = true }: EchoAssistAgentProps) {
  // Resolve config and point the non-React data layer (REST + WS) at the host's
  // API + auth, before children render so the first request uses the right base.
  const resolved = useMemo(() => {
    const next = resolveConfig(config)
    configureRuntime({
      apiBaseUrl: next.apiBaseUrl,
      wsBaseUrl: next.wsBaseUrl,
      useMocks: next.useMocks,
      getAuthToken: next.getAuthToken,
    })
    return next
  }, [config])

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false } },
      }),
  )

  const [selectedCallId, setSelectedCallId] = useState<string | null>(null)

  return (
    <AgentConfigProvider value={resolved}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={150}>
          <div className="echoassist-agent text-foreground">
            {selectedCallId ? (
              <CallDetailPage callId={selectedCallId} onBack={() => setSelectedCallId(null)} />
            ) : (
              <AgentDetailPage onOpenCall={setSelectedCallId} />
            )}
          </div>
          {renderToaster ? <Toaster /> : null}
        </TooltipProvider>
      </QueryClientProvider>
    </AgentConfigProvider>
  )
}
