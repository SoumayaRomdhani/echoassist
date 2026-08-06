import { format, formatDistanceToNowStrict, isToday, isValid, isYesterday } from 'date-fns'
import {
  Check,
  ChevronRight,
  Copy,
  FileText,
  MessageSquareText,
  Mic,
  PhoneCall,
} from 'lucide-react'
import { Fragment, type ReactNode, useState } from 'react'
import { ConsentBadge } from '@/components/ConsentBadge'
import { EmptyState } from '@/components/EmptyState'
import { StatusBadge } from '@/components/StatusBadge'
import { cn } from '@/lib/cn'
import { shortId } from '@/lib/format'
import type { CallOut } from '@/lib/types'

/** Non-terminal calls get the "live" accent rail + tint. */
function isLive(call: CallOut): boolean {
  return call.status === 'started' || call.status === 'interviewing'
}

/** Group calls into day buckets, preserving the incoming (newest-first) order. */
function groupByDay(calls: CallOut[]): { key: string; label: string; calls: CallOut[] }[] {
  const groups: { key: string; label: string; calls: CallOut[] }[] = []
  for (const call of calls) {
    const date = new Date(call.created_at)
    const key = isValid(date) ? format(date, 'yyyy-MM-dd') : 'unknown'
    const label = !isValid(date)
      ? 'Unknown date'
      : isToday(date)
        ? 'Today'
        : isYesterday(date)
          ? 'Yesterday'
          : format(date, 'EEEE, MMM d, yyyy')
    const last = groups.at(-1)
    if (last && last.key === key) last.calls.push(call)
    else groups.push({ key, label, calls: [call] })
  }
  return groups
}

export function CallList({
  calls,
  emptyAction,
  onSelect,
}: {
  calls: CallOut[]
  emptyAction?: ReactNode
  onSelect: (callId: string) => void
}) {
  if (calls.length === 0) {
    return (
      <EmptyState
        icon={PhoneCall}
        title="No calls yet"
        description="Start a screening call to see it here with a live transcript, structured notes, and a faithful post-call summary."
        action={emptyAction}
      />
    )
  }

  const groups = groupByDay(calls)

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <div className="w-full overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-border bg-foreground/[0.015]">
              <Th>Call</Th>
              <Th>Started</Th>
              <Th>Status</Th>
              <Th>Consent</Th>
              <Th>Artifacts</Th>
              <Th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group.key}>
                <tr>
                  <td colSpan={6} className="bg-foreground/[0.02] px-5 py-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                      {group.label}
                      <span className="ml-2 font-normal normal-case tracking-normal text-muted/60">
                        · {group.calls.length} {group.calls.length === 1 ? 'call' : 'calls'}
                      </span>
                    </span>
                  </td>
                </tr>
                {group.calls.map((call) => (
                  <CallRow key={call.call_id} call={call} onSelect={onSelect} />
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted">
        <span>
          {calls.length} {calls.length === 1 ? 'call' : 'calls'}
        </span>
      </div>
    </div>
  )
}

function CallRow({ call, onSelect }: { call: CallOut; onSelect: (id: string) => void }) {
  const live = isLive(call)
  const date = new Date(call.created_at)
  const valid = isValid(date)

  return (
    <tr
      className={cn(
        'group relative cursor-pointer border-b border-border transition-colors last:border-0',
        live ? 'bg-accent-3/[0.04] hover:bg-accent-3/[0.08]' : 'hover:bg-accent/[0.05]',
      )}
      onClick={() => onSelect(call.call_id)}
    >
      {/* Accent rail for live calls. */}
      <td className="relative w-0 p-0">
        {live && (
          <span className="absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-accent-3 to-accent-2" />
        )}
      </td>
      <td className="py-3 pl-5 pr-4 align-middle">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              'grid size-9 shrink-0 place-items-center rounded-xl',
              live ? 'bg-accent-3/12 text-accent-3' : 'bg-accent-2/12 text-accent-2',
            )}
          >
            <Mic className="size-4" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono text-xs text-foreground">
              {shortId(call.call_id, 10)}
              <CopyIdButton value={call.call_id} />
            </div>
            <div className="mt-0.5 text-[11px] capitalize text-muted/70">{call.domain}</div>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 align-middle">
        <div className="text-sm tabular-nums text-foreground">
          {valid ? format(date, 'MMM d · HH:mm') : call.created_at}
        </div>
        {valid && (
          <div className="text-[11px] text-muted/70">
            {formatDistanceToNowStrict(date, { addSuffix: true })}
          </div>
        )}
      </td>
      <td className="px-4 py-3 align-middle">
        <StatusBadge status={call.status} />
      </td>
      <td className="px-4 py-3 align-middle">
        <ConsentBadge granted={call.consent_granted} />
      </td>
      <td className="px-4 py-3 align-middle">
        <div className="flex items-center gap-2">
          <ArtifactPill icon={FileText} label="Notes" active={call.has_notes} />
          <ArtifactPill icon={MessageSquareText} label="Summary" active={call.has_summary} />
        </div>
      </td>
      <td className="py-3 pl-2 pr-5 align-middle">
        <ChevronRight className="size-4 text-muted/50 transition-all group-hover:translate-x-0.5 group-hover:text-accent" />
      </td>
    </tr>
  )
}

function ArtifactPill({
  icon: Icon,
  label,
  active,
}: {
  icon: typeof FileText
  label: string
  active: boolean
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium',
        active
          ? 'border-accent/30 bg-accent/[0.06] text-foreground'
          : 'border-border bg-foreground/[0.02] text-muted/40',
      )}
    >
      <Icon className="size-3" />
      {label}
    </span>
  )
}

function CopyIdButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      aria-label="Copy call id"
      className="text-muted/50 opacity-0 transition hover:text-accent focus-visible:opacity-100 group-hover:opacity-100"
      onClick={(e) => {
        e.stopPropagation()
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        })
      }}
    >
      {copied ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
    </button>
  )
}

function Th({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <th
      className={cn(
        'px-4 py-3 text-left align-middle text-[11px] font-semibold uppercase tracking-wider text-muted first:pl-5',
        className,
      )}
    >
      {children}
    </th>
  )
}
