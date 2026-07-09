import { AlertTriangle } from 'lucide-react'
import { BrandMark } from '@/components/BrandMark'
import { EmptyState } from '@/components/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAgentDomain } from '@/embed/AgentConfigContext'
import { CallList } from '@/features/calls/CallList'
import { StartCallDialog } from '@/features/calls/StartCallDialog'
import { DomainConfigPage } from '@/features/config/DomainConfigPage'
import { MetricsPage } from '@/features/metrics/MetricsPage'
import { ApiError } from '@/lib/api'
import { useCalls } from '@/lib/query'

export function AgentDetailPage({ onOpenCall }: { onOpenCall: (callId: string) => void }) {
  const domain = useAgentDomain()
  return (
    <div className="mx-auto max-w-7xl px-6 py-8 md:px-10">
      <div className="flex items-start gap-4">
        <div className="flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent/20 to-accent-2/20 ring-1 ring-accent/20">
          <BrandMark className="size-8" />
        </div>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-display text-3xl font-bold">
              <span className="bg-gradient-to-r from-accent to-accent-2 bg-clip-text text-transparent">
                EchoAssist
              </span>
            </h1>
            <Badge variant="ready">Ready</Badge>
          </div>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
            Autonomous voice agent — grounded answers, structured notes, and faithful post-call
            summaries.
          </p>
        </div>
      </div>

      <Tabs defaultValue="calls" className="mt-8">
        <TabsList>
          <TabsTrigger value="calls">Calls</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="config">Configuration</TabsTrigger>
        </TabsList>
        <TabsContent value="calls">
          <CallsTab domain={domain} onOpenCall={onOpenCall} />
        </TabsContent>
        <TabsContent value="metrics">
          <MetricsPage domain={domain} />
        </TabsContent>
        <TabsContent value="config">
          <DomainConfigPage defaultDomain={domain} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function CallsTab({
  domain,
  onOpenCall,
}: {
  domain: string
  onOpenCall: (callId: string) => void
}) {
  const { data, isLoading, isError, error } = useCalls({ domain, limit: 100 })

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-semibold capitalize">{domain} calls</h2>
          <p className="text-sm text-muted">
            Every call with its live transcript, structured notes, summary, and consent record.
          </p>
        </div>
        <StartCallDialog domain={domain} onStarted={onOpenCall} />
      </div>

      {isLoading ? (
        <Skeleton className="h-64 rounded-2xl" />
      ) : isError ? (
        <BackendError error={error} />
      ) : (
        <CallList
          calls={data?.items ?? []}
          onSelect={onOpenCall}
          emptyAction={<StartCallDialog domain={domain} onStarted={onOpenCall} />}
        />
      )}
    </div>
  )
}

function BackendError({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.status === 0
        ? 'Cannot reach the backend.'
        : error.detail
      : 'Something went wrong.'
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load calls"
      description={`${message} Check that the API is running, or set VITE_USE_MOCKS=true for the in-browser demo.`}
    />
  )
}
