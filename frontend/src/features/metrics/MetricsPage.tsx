import {
  BarChart3,
  CheckCircle2,
  FileText,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import { StatusBadge } from '@/components/StatusBadge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCalls } from '@/lib/query'
import type { CallStatus } from '@/lib/types'
import { computeMetrics } from './metrics'

const formatPct = (value: number) => `${Math.round(value * 100)}%`
const BREAKDOWN_ORDER: CallStatus[] = [
  'completed',
  'interviewing',
  'started',
  'declined',
  'failed',
]

export function MetricsPage({ domain }: { domain: string }) {
  const { data, isLoading } = useCalls({ domain, limit: 200 })

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-2xl" />
        ))}
      </div>
    )
  }

  const calls = data?.items ?? []
  const metrics = computeMetrics(calls)
  const stats: { label: string; value: string; icon: LucideIcon }[] = [
    { label: 'Total calls', value: String(metrics.total), icon: BarChart3 },
    { label: 'Completed', value: String(metrics.completed), icon: CheckCircle2 },
    { label: 'Consent rate', value: formatPct(metrics.consentRate), icon: ShieldCheck },
    { label: 'Notes coverage', value: formatPct(metrics.notesCoverage), icon: FileText },
  ]

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => {
          const Icon = stat.icon
          return (
            <Card key={stat.label} className="p-5">
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted">{stat.label}</p>
                <Icon className="size-4 text-accent" />
              </div>
              <p className="mt-3 font-display text-3xl font-bold tabular-nums">{stat.value}</p>
            </Card>
          )
        })}
      </div>

      <Card className="p-5">
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-muted">
          Outcome breakdown
        </h3>
        {metrics.total === 0 ? (
          <p className="mt-4 text-sm text-muted">No calls yet.</p>
        ) : (
          <div className="mt-4 space-y-3">
            {BREAKDOWN_ORDER.filter((status) => metrics.byStatus[status] > 0).map((status) => {
              const count = metrics.byStatus[status]
              return (
                <div key={status} className="flex items-center gap-4">
                  <div className="w-32 shrink-0">
                    <StatusBadge status={status} />
                  </div>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-foreground/[0.06]">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: formatPct(count / metrics.total) }}
                    />
                  </div>
                  <span className="w-10 text-right text-sm tabular-nums text-muted">{count}</span>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      
    </div>
  )
}
