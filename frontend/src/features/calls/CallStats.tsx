import { CheckCircle2, PhoneCall, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import type { CallOut } from '@/lib/types'

/**
 * The KPI band above the calls table: total volume, consent rate, completion,
 * and how many calls are live right now. Every figure is derived from the same
 * `CallOut[]` the table renders — no extra fetch, so the band always agrees with
 * the rows below it.
 */
export function CallStats({ calls }: { calls: CallOut[] }) {
  const total = calls.length
  const consented = calls.filter((c) => c.consent_granted).length
  const completed = calls.filter((c) => c.status === 'completed').length
  const live = calls.filter((c) => c.status === 'started' || c.status === 'interviewing').length

  const consentRate = total ? Math.round((consented / total) * 100) : 0
  const completionRate = total ? Math.round((completed / total) * 100) : 0

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile
        icon={<PhoneCall className="size-3.5" />}
        label="Total calls"
        value={total}
        hint="in this workspace"
      />
      <Tile
        icon={<ShieldCheck className="size-3.5" />}
        label="Consent rate"
        value={`${consentRate}%`}
        hint={`${consented} of ${total} consented`}
        accessory={<Ring value={consentRate} />}
      />
      <Tile
        icon={<CheckCircle2 className="size-3.5" />}
        label="Completed"
        value={completed}
        hint={`${completionRate}% completion`}
      />
      <Tile
        icon={
          <span className="relative flex size-2">
            <span
              className={cn(
                'absolute inline-flex size-full rounded-full bg-accent-3 opacity-75',
                live > 0 && 'motion-safe:animate-ping',
              )}
            />
            <span className="relative inline-flex size-2 rounded-full bg-accent-3" />
          </span>
        }
        label="Live now"
        value={live}
        hint={live === 1 ? 'call in progress' : 'calls in progress'}
        highlight={live > 0}
      />
    </div>
  )
}

function Tile({
  icon,
  label,
  value,
  hint,
  accessory,
  highlight,
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  hint: string
  accessory?: ReactNode
  highlight?: boolean
}) {
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-2xl border border-border bg-surface p-4 shadow-sm',
        highlight && 'border-accent-3/30',
      )}
    >
      <div className="flex items-center gap-1.5 text-xs font-semibold text-muted">
        <span className={cn(highlight ? 'text-accent-3' : 'text-muted')}>{icon}</span>
        {label}
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span className="font-display text-2xl font-semibold tabular-nums tracking-tight">
          {value}
        </span>
        {accessory}
      </div>
      <div className="mt-0.5 text-[11px] text-muted/70">{hint}</div>
    </div>
  )
}

/** A compact progress ring; `value` is a 0–100 percentage. */
function Ring({ value }: { value: number }) {
  const r = 15
  const circumference = 2 * Math.PI * r
  const dash = (value / 100) * circumference
  return (
    <svg className="size-8 -rotate-90" viewBox="0 0 36 36" aria-hidden>
      <circle cx="18" cy="18" r={r} fill="none" stroke="currentColor" className="text-border" strokeWidth="4" />
      <circle
        cx="18"
        cy="18"
        r={r}
        fill="none"
        stroke="currentColor"
        className="text-emerald-500"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circumference}`}
      />
    </svg>
  )
}
