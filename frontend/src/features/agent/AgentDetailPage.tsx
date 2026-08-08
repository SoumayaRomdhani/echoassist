import { BrandMark } from '@/components/BrandMark'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAgentDomain } from '@/embed/AgentConfigContext'
import { supportsInterviews } from '@/embed/types'
import { CallsTab } from '@/features/calls/CallsTab'
import { DomainConfigPage } from '@/features/config/DomainConfigPage'
import { JobPostingsTab } from '@/features/jobs/JobPostingsTab'
import { MetricsPage } from '@/features/metrics/MetricsPage'

export function AgentDetailPage({ onOpenCall }: { onOpenCall: (callId: string) => void }) {
  const domain = useAgentDomain()
  const showInterviews = supportsInterviews(domain)
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
          {showInterviews && <TabsTrigger value="interviews">Interviews</TabsTrigger>}
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="config">Configuration</TabsTrigger>
        </TabsList>
        <TabsContent value="calls">
          <CallsTab domain={domain} onOpenCall={onOpenCall} />
        </TabsContent>
        {showInterviews && (
          <TabsContent value="interviews">
            <JobPostingsTab domain={domain} />
          </TabsContent>
        )}
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

