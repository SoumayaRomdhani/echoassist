import { cn } from '@/lib/cn'
import type { AgentState } from '@/lib/types'
import type { CallProgress } from '@/lib/ws'
import { AgentOrb } from './AgentOrb'

/**
 * The live "call stage" shown above the transcript while a call is running: the
 * ambient {@link AgentOrb}, an explicit (screen-reader-announced) phase label, and
 * the structured-interview progress. Purely presentational — it renders the folded
 * live state and holds no socket of its own.
 */

const PHASE: Record<AgentState, { label: string; className: string }> = {
  idle: { label: 'Standing by', className: 'text-muted' },
  listening: { label: 'Listening…', className: 'text-accent' },
  thinking: { label: 'Thinking…', className: 'text-[var(--c-accent-2)]' },
  speaking: { label: 'Speaking', className: 'text-accent' },
}

export function LiveCallStage({
  agentState,
  volume,
  progress,
  step,
}: {
  agentState: AgentState
  volume: number | null
  progress: CallProgress | null
  /** Concrete pipeline sub-step ("Searching the knowledge base…"); overrides the phase label. */
  step?: string | null
}) {
  const phase = PHASE[agentState]

  return (
    <section className="flex flex-col items-center gap-5 rounded-2xl border border-border bg-surface px-6 py-8">
      <AgentOrb state={agentState} volume={volume} />

      <div className="flex flex-col items-center gap-1.5">
        <p
          aria-live="polite"
          className={cn('font-display text-lg font-semibold tracking-tight', phase.className)}
        >
          {step ?? phase.label}
        </p>
        {progress ? (
          <p className="text-xs font-medium uppercase tracking-wide text-muted">
            Question {progress.index} of {progress.total}
          </p>
        ) : null}
      </div>

      {progress ? (
        <div
          className="flex w-full max-w-xs gap-1.5"
          role="progressbar"
          aria-valuenow={progress.index}
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-label="Interview progress"
        >
          {Array.from({ length: progress.total }, (_, i) => (
            <span
              key={i}
              className={cn(
                'h-1.5 flex-1 rounded-full transition-colors duration-500',
                i < progress.index ? 'bg-accent' : 'bg-foreground/[0.1]',
              )}
            />
          ))}
        </div>
      ) : null}
    </section>
  )
}
