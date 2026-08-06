import { AlertTriangle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { ApiError } from '@/lib/api'
import { useCalls } from '@/lib/query'
import type { CallOut } from '@/lib/types'
import { CallList } from './CallList'
import { LiveCallsBanner } from './LiveCallsBanner'
import { StartCallDialog } from './StartCallDialog'

type StatusFilter = 'all' | 'live' | 'completed' | 'declined'

const FILTERS: { key: StatusFilter; label: string; match: (c: CallOut) => boolean }[] = [
  { key: 'all', label: 'All', match: () => true },
  {
    key: 'live',
    label: 'Live',
    match: (c) => c.status === 'started' || c.status === 'interviewing',
  },
  { key: 'completed', label: 'Completed', match: (c) => c.status === 'completed' },
  {
    key: 'declined',
    label: 'Declined',
    match: (c) => c.status === 'declined' || c.status === 'failed',
  },
]

/**
 * The Calls section: start a call, KPI band, the live-now banner, a status filter,
 * and the list of every call with its transcript, notes, summary, and consent
 * record. Extracted so both the embedded tabs and the host shell's sidebar can
 * render it.
 */
export function CallsTab({
  domain,
  query = '',
  onOpenCall,
}: {
  domain: string
  query?: string
  onOpenCall: (callId: string) => void
}) {
  const { data, isLoading, isError, error } = useCalls({ domain, limit: 100 })
  const [status, setStatus] = useState<StatusFilter>('all')

  const q = query.trim().toLowerCase()
  // Base set = everything matching the header search. Stats and the filter chip
  // counts are computed over this set so they always agree with what's on screen.
  const base = useMemo(
    () =>
      (data?.items ?? []).filter(
        (c) =>
          !q ||
          c.call_id.toLowerCase().includes(q) ||
          c.domain.toLowerCase().includes(q) ||
          c.status.toLowerCase().includes(q),
      ),
    [data?.items, q],
  )

  const activeFilter = FILTERS.find((f) => f.key === status) ?? FILTERS[0]
  const items = base.filter(activeFilter.match)

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

      <LiveCallsBanner domain={domain} onOpenCall={onOpenCall} />

      {isLoading ? (
        <div className="space-y-5">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : isError ? (
        <BackendError error={error} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1 rounded-xl border border-border bg-surface p-1 shadow-sm sm:w-fit">
            {FILTERS.map((f) => {
              const count = base.filter(f.match).length
              const selected = f.key === status
              return (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setStatus(f.key)}
                  aria-pressed={selected}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors',
                    selected
                      ? 'bg-accent/15 text-foreground ring-1 ring-inset ring-accent/30'
                      : 'text-muted hover:text-foreground',
                  )}
                >
                  {f.key === 'live' && (
                    <span className="size-1.5 rounded-full bg-accent-3" aria-hidden />
                  )}
                  {f.label}
                  <span className="tabular-nums text-muted/60">{count}</span>
                </button>
              )
            })}
          </div>

          <CallList
            calls={items}
            onSelect={onOpenCall}
            emptyAction={
              q || status !== 'all' ? undefined : (
                <StartCallDialog domain={domain} onStarted={onOpenCall} />
              )
            }
          />
        </>
      )}
    </div>
  )
}

export function BackendError({ error }: { error: unknown }) {
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
