import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Radio } from 'lucide-react'
import { useEffect } from 'react'
import { ConsentBadge } from '@/components/ConsentBadge'
import { StatusBadge } from '@/components/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { useCallEvents } from '@/hooks/useCallEvents'
import { ApiError } from '@/lib/api'
import { formatDateTime, shortId } from '@/lib/format'
import { useCall } from '@/lib/query'
import type { CallStatus } from '@/lib/types'
import { ConsentPanel } from './ConsentPanel'
import { LiveCallStage } from './LiveCallStage'
import { NotesPanel } from './NotesPanel'
import { SummaryPanel } from './SummaryPanel'
import { TranscriptView } from './TranscriptView'

const TERMINAL: CallStatus[] = ['completed', 'declined', 'failed']

export function CallDetailPage({ callId, onBack }: { callId: string; onBack: () => void }) {
  const queryClient = useQueryClient()

  const detailQuery = useCall(callId)
  const persisted = detailQuery.data
  const persistedTerminal = persisted ? TERMINAL.includes(persisted.status) : false

  // Subscribe to live events while the call is not yet a persisted terminal record.
  const live = useCallEvents(callId, !persistedTerminal)

  // When the live stream finishes, pull the canonical persisted record (detail +
  // consent log, both keyed under ['calls']).
  useEffect(() => {
    if (live.done) {
      void queryClient.invalidateQueries({ queryKey: ['calls'] })
    }
  }, [live.done, queryClient])

  const status: CallStatus | null = persistedTerminal
    ? persisted!.status
    : (live.status ?? persisted?.status ?? null)
  const isRunning = status === 'started' || status === 'interviewing'
  const showLive = !persistedTerminal && !live.done && (live.connected || isRunning)

  const turns =
    !persistedTerminal && live.turns.length > 0 ? live.turns : (persisted?.transcript ?? live.turns)
  const notes = persistedTerminal
    ? persisted!.notes
    : (live.notes ?? persisted?.notes ?? null)
  const summary = persistedTerminal
    ? persisted!.summary
    : (live.summary ?? persisted?.summary ?? null)
  const consentGranted = persisted?.consent_granted ?? live.consent?.granted ?? false
  const liveError = persistedTerminal ? null : live.error

  const hasAnyData = Boolean(persisted) || live.turns.length > 0 || status !== null
  const isMissing =
    detailQuery.isError &&
    detailQuery.error instanceof ApiError &&
    detailQuery.error.status === 404 &&
    !hasAnyData &&
    live.done

  return (
    <div className="mx-auto max-w-6xl px-6 py-8 md:px-10">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Back to calls
      </button>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <h1 className="font-display text-2xl font-bold">Call</h1>
        <span className="font-mono text-sm text-muted">{shortId(callId, 12)}</span>
        {status ? <StatusBadge status={status} /> : null}
        <ConsentBadge granted={consentGranted} />
        {showLive ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--c-accent-3)]">
            <Radio className="size-3.5 animate-pulse" />
            Live
          </span>
        ) : null}
        {persisted ? (
          <span className="ml-auto text-sm text-muted">{formatDateTime(persisted.created_at)}</span>
        ) : null}
      </div>

      {liveError ? (
        <div className="mt-5 flex items-start gap-2 rounded-xl border border-[var(--c-accent-3)]/30 bg-[var(--c-accent-3)]/10 px-4 py-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[var(--c-accent-3)]" />
          <span>{liveError.message}</span>
        </div>
      ) : null}

      {isMissing ? (
        <p className="mt-10 rounded-2xl border border-dashed border-border bg-surface/50 px-6 py-14 text-center text-muted">
          This call could not be found. It may still be starting, or the id is incorrect.
        </p>
      ) : !hasAnyData && detailQuery.isLoading ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <Skeleton className="h-[60vh] rounded-2xl" />
          <Skeleton className="h-[60vh] rounded-2xl" />
        </div>
      ) : (
        <div className="mt-6 grid items-start gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-6">
            {showLive ? (
              <LiveCallStage
                agentState={live.agentState}
                volume={live.volume}
                progress={live.progress}
              />
            ) : null}
            <TranscriptView turns={turns} live={showLive} partial={showLive ? live.partial : null} />
          </div>
          <div className="space-y-6">
            <NotesPanel notes={notes} />
            <SummaryPanel summary={summary} />
            <ConsentPanel callId={callId} />
          </div>
        </div>
      )}
    </div>
  )
}
