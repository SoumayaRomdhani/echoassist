import { cn } from '@/lib/cn'
import type { AgentState } from '@/lib/types'
import type { CallProgress } from '@/lib/ws'

/**
 * The compact live-status chip in the transcript header: a small audio-reactive orb
 * (colour + pulse convey the phase) next to a short phase label and the interview
 * progress. It replaces the large orb stage — the transcript is the hero now, and the
 * *detailed* pipeline step ("Searching the knowledge base…") lives in the flow, on the
 * shimmering placeholder reply. This is the at-a-glance summary; the flow has the detail.
 */

const PHASE: Record<AgentState, { label: string; text: string; dot: string; pulse: string }> = {
  idle: { label: 'Standing by', text: 'text-muted', dot: 'bg-muted', pulse: '2.4s' },
  listening: { label: 'Listening…', text: 'text-accent', dot: 'bg-accent', pulse: '1.6s' },
  thinking: {
    label: 'Thinking…',
    text: 'text-[var(--c-accent-2)]',
    dot: 'bg-[var(--c-accent-2)]',
    pulse: '2s',
  },
  speaking: { label: 'Speaking', text: 'text-emerald-500', dot: 'bg-emerald-500', pulse: '0.9s' },
}

export function LiveStatus({
  agentState,
  progress,
}: {
  agentState: AgentState
  progress: CallProgress | null
}) {
  const phase = PHASE[agentState]
  return (
    <div className="flex items-center gap-2">
      <span className="relative flex size-2.5 items-center justify-center" aria-hidden="true">
        <span
          className={cn('absolute inline-flex size-2.5 animate-ping rounded-full opacity-40', phase.dot)}
          style={{ animationDuration: phase.pulse }}
        />
        <span className={cn('relative inline-flex size-2 rounded-full', phase.dot)} />
      </span>
      <span aria-live="polite" className={cn('font-display text-xs font-semibold', phase.text)}>
        {phase.label}
      </span>
      {progress ? (
        <span className="text-xs font-medium text-muted">
          · Question {progress.index}/{progress.total}
        </span>
      ) : null}
    </div>
  )
}
