import { ChevronRight, Radio } from 'lucide-react'
import { StatusBadge } from '@/components/StatusBadge'
import { shortId } from '@/lib/format'
import { useLiveCalls } from '@/lib/query'

/**
 * A dedicated "live now" banner above the calls list: it polls `/calls/live` and,
 * when a call is in progress (including one taken at the microphone and bridged in),
 * surfaces it as a one-click entry into the live view. Renders nothing when idle, so
 * it costs no space in the common case.
 */
export function LiveCallsBanner({
  domain,
  onOpenCall,
}: {
  domain: string
  onOpenCall: (callId: string) => void
}) {
  const { data } = useLiveCalls(domain)
  const calls = data ?? []
  if (calls.length === 0) return null

  return (
    <section
      aria-label="Live calls"
      className="rounded-2xl border border-[var(--c-accent-3)]/30 bg-[var(--c-accent-3)]/[0.06] p-4"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <Radio className="size-4 animate-pulse text-[var(--c-accent-3)]" />
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-[var(--c-accent-3)]">
          Live now
        </h3>
      </div>
      <ul className="space-y-2">
        {calls.map((call) => (
          <li key={call.call_id}>
            <button
              type="button"
              onClick={() => onOpenCall(call.call_id)}
              className="group flex w-full items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-[var(--c-accent-3)]/40"
            >
              <StatusBadge status={call.status} />
              <span className="font-mono text-xs text-muted">{shortId(call.call_id, 12)}</span>
              <span className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-[var(--c-accent-3)]">
                Open live
                <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
