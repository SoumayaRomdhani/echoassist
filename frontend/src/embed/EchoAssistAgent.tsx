import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AgentDetailPage } from '@/features/agent/AgentDetailPage'
import { CallDetailPage } from '@/features/calls/CallDetailPage'
import { CallsTab } from '@/features/calls/CallsTab'
import { DomainConfigPage } from '@/features/config/DomainConfigPage'
import { JobPostingsTab } from '@/features/jobs/JobPostingsTab'
import { MetricsPage } from '@/features/metrics/MetricsPage'
import { OverviewPage } from '@/features/overview/OverviewPage'
import { configureRuntime } from '@/lib/runtimeConfig'
import '@/styles/index.css'
import { AgentConfigProvider } from './AgentConfigContext'
import {
  resolveConfig,
  supportsInterviews,
  type AgentSection,
  type EchoAssistConfig,
} from './types'

export interface EchoAssistAgentProps {
  config: EchoAssistConfig
  /** Render an internal toast host. Set false if the host page already mounts one. */
  renderToaster?: boolean
  /**
   * Controlled workspace section. When provided, the host's shell drives navigation and
   * the agent renders that section without its own tabs. When omitted, the agent is fully
   * self-contained with an internal tab bar (the default embed contract for ACTEEK).
   */
  section?: AgentSection
  /** Section changes the agent initiates itself (e.g. "See all calls" from Overview). */
  onSection?: (section: AgentSection) => void
  /** Free-text filter from the host search bar, applied to the calls list. */
  query?: string
}

/**
 * The embeddable EchoAssist agent — the Sprint 7 deliverable.
 *
 * Self-contained: it brings its own data layer (TanStack Query) and tooltip host, and
 * drives list↔detail navigation with local state (no router). ACTEEK mounts it with one
 * line: `<EchoAssistAgent config={{ apiBaseUrl, getAuthToken }} />`. It does NOT render the
 * marketplace, sidebar, or login — those belong to ACTEEK (ARCHITECTURE.md §2). Theme is
 * inherited from the host's `[data-theme]` via the shared `--c-*` tokens.
 */
export function EchoAssistAgent({
  config,
  renderToaster = true,
  section,
  onSection,
  query = '',
}: EchoAssistAgentProps) {
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
  // Switching section (via the host sidebar) closes any open call detail.
  useEffect(() => setSelectedCallId(null), [section])

  const domain = resolved.domain
  // Interviews is screening-only; if a host requests it elsewhere, show Overview.
  const effective =
    section === 'interviews' && !supportsInterviews(domain) ? 'overview' : section

  let body
  if (selectedCallId) {
    body = <CallDetailPage callId={selectedCallId} onBack={() => setSelectedCallId(null)} />
  } else if (effective) {
    body = (
      <div className="mx-auto max-w-7xl px-6 py-8 md:px-8">
        {effective === 'overview' ? (
          <OverviewPage
            domain={domain}
            query={query}
            onOpenCall={setSelectedCallId}
            onSeeAllCalls={() => onSection?.('calls')}
          />
        ) : effective === 'calls' ? (
          <CallsTab domain={domain} query={query} onOpenCall={setSelectedCallId} />
        ) : effective === 'interviews' ? (
          <JobPostingsTab domain={domain} />
        ) : effective === 'metrics' ? (
          <MetricsPage domain={domain} />
        ) : (
          <DomainConfigPage defaultDomain={domain} />
        )}
      </div>
    )
  } else {
    body = <AgentDetailPage onOpenCall={setSelectedCallId} />
  }

  return (
    <AgentConfigProvider value={resolved}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={150}>
          <div className="echoassist-agent text-foreground">{body}</div>
          {renderToaster ? <Toaster /> : null}
        </TooltipProvider>
      </QueryClientProvider>
    </AgentConfigProvider>
  )
}
