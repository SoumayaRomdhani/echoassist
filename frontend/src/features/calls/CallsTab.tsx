import { AlertTriangle } from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useCalls } from '@/lib/query'
import { CallList } from './CallList'
import { LiveCallsBanner } from './LiveCallsBanner'
import { StartCallDialog } from './StartCallDialog'

/**
 * The Calls section: start a call, the live-now banner, and the list of every call
 * with its transcript, notes, summary, and consent record. Extracted so both the
 * embedded tabs and the host shell's sidebar can render it.
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
  const q = query.trim().toLowerCase()
  const items = (data?.items ?? []).filter(
    (c) =>
      !q ||
      c.call_id.toLowerCase().includes(q) ||
      c.domain.toLowerCase().includes(q) ||
      c.status.toLowerCase().includes(q),
  )

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
        <Skeleton className="h-64 rounded-2xl" />
      ) : isError ? (
        <BackendError error={error} />
      ) : (
        <CallList
          calls={items}
          onSelect={onOpenCall}
          emptyAction={q ? undefined : <StartCallDialog domain={domain} onStarted={onOpenCall} />}
        />
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
