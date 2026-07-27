import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  ChevronRight,
  FileText,
  Minus,
  PhoneCall,
  Radio,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { computeMetrics } from '@/features/metrics/metrics'
import { cn } from '@/lib/cn'
import { formatRelative, shortId, titleCase } from '@/lib/format'
import { useCalls, useLiveCalls } from '@/lib/query'
import type { CallOut, CallStatus } from '@/lib/types'

const DAY = 86_400_000
const HOUR = 3_600_000
const pct = (v: number) => `${Math.round(v * 100)}%`
const rate = (a: number, b: number) => (b ? a / b : 0)

type Range = 'Day' | 'Week' | 'Month'
type Filter = 'All' | 'Completed' | 'Declined'

/**
 * The workspace home — a SaaS overview built entirely from the calls API. All controls
 * are live: the chart range re-buckets, the table filter and the top-bar search filter
 * the recent calls. Deltas are real week-over-week (last 7 days vs the 7 before), and
 * read "new" when there's no prior baseline — never fabricated.
 */
export function OverviewPage({
  domain,
  query = '',
  onOpenCall,
  onSeeAllCalls,
}: {
  domain: string
  query?: string
  onOpenCall: (callId: string) => void
  onSeeAllCalls: () => void
}) {
  const { data, isLoading } = useCalls({ domain, limit: 200 })
  const { data: liveData } = useLiveCalls(domain)
  const [range, setRange] = useState<Range>('Week')
  const [filter, setFilter] = useState<Filter>('All')

  if (isLoading) {
    return (
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-2xl" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <Skeleton className="h-72 rounded-2xl" />
          <Skeleton className="h-72 rounded-2xl" />
        </div>
      </div>
    )
  }

  const calls = data?.items ?? []
  const live = liveData?.[0]
  const now = Date.now()
  const inWindow = (c: CallOut, from: number, to: number) => {
    const age = now - new Date(c.created_at).getTime()
    return age >= from && age < to
  }
  const week = calls.filter((c) => inWindow(c, 0, 7 * DAY))
  const prev = calls.filter((c) => inWindow(c, 7 * DAY, 14 * DAY))

  const m = computeMetrics(calls)
  const mW = computeMetrics(week)
  const mP = computeMetrics(prev)
  const rd = (a: number, b: number) => (prev.length ? Math.round((a - b) * 100) : null)

  const tiles: TileData[] = [
    { label: 'Calls handled', value: String(m.total), hint: `${week.length} this week`, icon: PhoneCall, tone: 'accent', delta: week.length - prev.length, unit: '' },
    { label: 'Completion rate', value: pct(rate(m.completed, m.total)), hint: 'interviews reaching close', icon: BarChart3, tone: 'emerald', delta: rd(rate(mW.completed, mW.total), rate(mP.completed, mP.total)), unit: 'pt' },
    { label: 'Consent captured', value: pct(m.consentRate), hint: 'audit trail complete', icon: ShieldCheck, tone: 'violet', delta: rd(mW.consentRate, mP.consentRate), unit: 'pt' },
    { label: 'Notes coverage', value: pct(m.notesCoverage), hint: 'structured notes on file', icon: FileText, tone: 'pink', delta: rd(mW.notesCoverage, mP.notesCoverage), unit: 'pt' },
  ]

  const chart = buckets(calls, range, now)

  // Recent calls: apply the segmented filter and the top-bar search, live call pinned first.
  const q = query.trim().toLowerCase()
  const matchesFilter = (c: CallOut) =>
    filter === 'All' ||
    (filter === 'Completed' && c.status === 'completed') ||
    (filter === 'Declined' && c.status === 'declined')
  const matchesQuery = (c: CallOut) =>
    !q || c.call_id.toLowerCase().includes(q) || c.domain.toLowerCase().includes(q) || c.status.toLowerCase().includes(q)
  const filtered = calls.filter((c) => matchesFilter(c) && matchesQuery(c))
  const showLive = live && matchesFilter(live) && matchesQuery(live)
  const recent = (showLive ? [live, ...filtered.filter((c) => c.call_id !== live.call_id)] : filtered).slice(0, 6)

  return (
    <div className="space-y-5">
      {live ? (
        <button
          type="button"
          onClick={() => onOpenCall(live.call_id)}
          className="group flex w-full items-center gap-3 rounded-2xl border border-[var(--c-accent-3)]/40 bg-gradient-to-r from-[var(--c-accent-3)]/[0.1] to-surface px-5 py-3.5 text-left"
        >
          <Radio className="size-4 animate-pulse text-[var(--c-accent-3)]" />
          <span className="font-display text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--c-accent-3)]">Live now</span>
          <span className="font-medium">{titleCase(live.domain)} call</span>
          <span className="text-sm text-muted">· started {formatRelative(live.created_at)}</span>
          <span className="ml-auto inline-flex items-center gap-1 text-sm font-semibold text-[var(--c-accent-3)]">
            Open live <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </span>
        </button>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((t) => (
          <StatTile key={t.label} {...t} />
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Panel
          title="Calls this week"
          sub={RANGE_SUB[range]}
          right={<Segmented options={['Day', 'Week', 'Month']} value={range} onChange={(v) => setRange(v as Range)} />}
        >
          <AreaChart values={chart.values} axis={chart.axis} />
        </Panel>

        <Panel title="Outcomes" sub={`last ${m.total} calls`}>
          <OutcomeDonut metrics={m} liveCount={live ? 1 : 0} />
        </Panel>
      </section>

      <Panel
        title="Recent calls"
        sub={q ? `matching “${query.trim()}”` : 'live transcript, notes, summary & consent per call'}
        right={
          <div className="flex items-center gap-3">
            <Segmented options={['All', 'Completed', 'Declined']} value={filter} onChange={(v) => setFilter(v as Filter)} />
            <button type="button" onClick={onSeeAllCalls} className="text-sm font-medium text-accent transition-opacity hover:opacity-80">
              See all
            </button>
          </div>
        }
        flush
      >
        <RecentCalls calls={recent} liveId={live?.call_id} onOpenCall={onOpenCall} />
      </Panel>
    </div>
  )
}

const RANGE_SUB: Record<Range, string> = {
  Day: 'new calls per hour, last 24h',
  Week: 'new calls per day, last 7 days',
  Month: 'new calls per day, last 30 days',
}

/* ---------- tiles ---------- */
interface TileData {
  label: string; value: string; hint: string; icon: LucideIcon
  tone: 'accent' | 'emerald' | 'violet' | 'pink'; delta: number | null; unit: string
}
const TONE: Record<TileData['tone'], string> = {
  accent: 'bg-accent/12 text-accent',
  emerald: 'bg-emerald-500/12 text-emerald-500',
  violet: 'bg-[var(--c-accent-2)]/14 text-[var(--c-accent-2)]',
  pink: 'bg-[var(--c-accent-3)]/12 text-[var(--c-accent-3)]',
}
function StatTile({ label, value, hint, icon: Icon, tone, delta, unit }: TileData) {
  const Arrow = delta == null || delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight
  const dc =
    delta != null && delta > 0 ? 'text-emerald-500'
      : delta != null && delta < 0 ? 'text-[var(--c-accent-3)]' : 'text-muted'
  const dl = delta == null ? 'new' : delta === 0 ? 'stable' : `${Math.abs(delta)}${unit}`
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center gap-2.5">
        <span className={cn('grid size-8 place-items-center rounded-lg', TONE[tone])}>
          <Icon className="size-[18px]" />
        </span>
        <p className="text-sm font-medium text-muted">{label}</p>
      </div>
      <div className="mt-3 flex items-end justify-between">
        <p className="font-display text-[28px] font-bold leading-none tabular-nums">{value}</p>
        <span className={cn('inline-flex items-center gap-0.5 text-xs font-semibold', dc)}>
          <Arrow className="size-3.5" />
          {dl}
        </span>
      </div>
      <p className="mt-1.5 text-xs text-muted">{hint}</p>
    </div>
  )
}

/* ---------- panel + segmented ---------- */
function Panel({
  title, sub, right, flush, children,
}: {
  title: string; sub?: string; right?: ReactNode; flush?: boolean; children: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <h3 className="font-display text-[15px] font-semibold">{title}</h3>
          {sub ? <p className="truncate text-xs text-muted">{sub}</p> : null}
        </div>
        {right}
      </div>
      <div className={flush ? '' : 'p-5'}>{children}</div>
    </section>
  )
}

function Segmented({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex shrink-0 gap-0.5 rounded-lg border border-border bg-foreground/[0.03] p-0.5">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          className={cn(
            'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
            o === value ? 'bg-surface text-foreground shadow-sm' : 'text-muted hover:text-foreground',
          )}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

/* ---------- area chart ---------- */
function buckets(calls: CallOut[], range: Range, now: number): { values: number[]; axis: string[] } {
  const count = (from: number, span: number) =>
    calls.filter((c) => {
      const t = new Date(c.created_at).getTime()
      return t >= from && t < from + span
    }).length

  if (range === 'Day') {
    const base = new Date(now)
    base.setMinutes(0, 0, 0)
    const start = base.getTime() - 23 * HOUR
    const values = Array.from({ length: 24 }, (_, i) => count(start + i * HOUR, HOUR))
    return { values, axis: ['24h', '18h', '12h', '6h', 'now'] }
  }
  if (range === 'Month') {
    const base = new Date(now)
    base.setHours(0, 0, 0, 0)
    const start = base.getTime() - 29 * DAY
    const values = Array.from({ length: 30 }, (_, i) => count(start + i * DAY, DAY))
    return { values, axis: ['30d', '3w', '2w', '1w', 'now'] }
  }
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const base = new Date(now)
  base.setHours(0, 0, 0, 0)
  const start = base.getTime() - 6 * DAY
  const values = Array.from({ length: 7 }, (_, i) => count(start + i * DAY, DAY))
  const axis = Array.from({ length: 7 }, (_, i) => days[new Date(start + i * DAY).getDay()])
  return { values, axis }
}
function AreaChart({ values, axis }: { values: number[]; axis: string[] }) {
  const W = 640
  const H = 180
  const max = Math.max(1, ...values)
  const x = (i: number) => (values.length <= 1 ? W / 2 : (i / (values.length - 1)) * W)
  const y = (v: number) => H - 14 - (v / max) * (H - 34)
  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' L ')
  const peak = values.reduce((a, v, i) => (v >= values[a] ? i : a), 0)
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Calls over time">
        <defs>
          <linearGradient id="ov-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--c-accent)" stopOpacity="0.28" />
            <stop offset="1" stopColor="var(--c-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((g) => (
          <line key={g} x1="0" y1={H - 14 - g * (H - 34)} x2={W} y2={H - 14 - g * (H - 34)} stroke="var(--c-border)" strokeWidth="1" />
        ))}
        <path d={`M ${line} L ${W},${H} L 0,${H} Z`} fill="url(#ov-fill)" />
        <path d={`M ${line}`} fill="none" stroke="var(--c-accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={x(peak)} cy={y(values[peak])} r="4.5" fill="var(--c-accent)" stroke="var(--c-surface)" strokeWidth="2" />
      </svg>
      <div className="mt-2 flex justify-between text-xs tabular-nums text-muted">
        {axis.map((a, i) => (
          <span key={i}>{a}</span>
        ))}
      </div>
    </>
  )
}

/* ---------- donut ---------- */
const OUTCOME: { status: CallStatus; label: string; color: string }[] = [
  { status: 'completed', label: 'Completed', color: '#34D399' },
  { status: 'declined', label: 'Declined', color: 'var(--c-text-muted)' },
  { status: 'failed', label: 'Failed', color: 'var(--c-accent-3)' },
]
function OutcomeDonut({ metrics, liveCount }: { metrics: ReturnType<typeof computeMetrics>; liveCount: number }) {
  const total = metrics.total
  const segs = OUTCOME.map((o) => ({ ...o, count: metrics.byStatus[o.status] })).filter((s) => s.count > 0)
  const legend = [...segs, { status: 'live' as const, label: 'Live now', color: 'var(--c-accent)', count: liveCount }].filter((s) => s.count > 0)
  const R = 15.9155
  let offset = 25
  return (
    <div className="flex items-center gap-6">
      <div className="relative grid size-[132px] shrink-0 place-items-center">
        <svg viewBox="0 0 42 42" className="size-full">
          <circle cx="21" cy="21" r={R} fill="none" stroke="var(--c-border)" strokeWidth="4.5" />
          {total === 0
            ? null
            : segs.map((s) => {
                const share = (s.count / total) * 100
                const el = (
                  <circle key={s.status} cx="21" cy="21" r={R} fill="none" stroke={s.color} strokeWidth="4.5" strokeDasharray={`${share} ${100 - share}`} strokeDashoffset={offset} strokeLinecap="round" />
                )
                offset -= share
                return el
              })}
        </svg>
        <div className="absolute text-center">
          <span className="block font-display text-2xl font-bold tabular-nums">{pct(rate(metrics.completed, total))}</span>
          <span className="text-[11px] text-muted">completed</span>
        </div>
      </div>
      <ul className="flex-1 space-y-2.5">
        {legend.map((s) => (
          <li key={s.status} className="flex items-center gap-2.5 text-sm">
            <span className="size-2.5 rounded" style={{ background: s.color }} />
            {s.label}
            <span className="ml-auto font-medium tabular-nums text-muted">{s.count}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ---------- recent calls table ---------- */
const PILL: Record<string, string> = {
  completed: 'text-emerald-500 bg-emerald-500/12',
  interviewing: 'text-accent bg-accent/12',
  started: 'text-accent bg-accent/12',
  live: 'text-[var(--c-accent-3)] bg-[var(--c-accent-3)]/12',
  declined: 'text-muted bg-foreground/[0.06]',
  failed: 'text-[var(--c-accent-3)] bg-[var(--c-accent-3)]/12',
}
function Pill({ status, label }: { status: string; label: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', PILL[status] ?? PILL.declined)}>
      <span className="size-1.5 rounded-full bg-current" />
      {label}
    </span>
  )
}
function RecentCalls({ calls, liveId, onOpenCall }: { calls: CallOut[]; liveId?: string; onOpenCall: (id: string) => void }) {
  if (calls.length === 0) {
    return <p className="px-5 py-10 text-center text-sm text-muted">No calls match.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-muted">
            <th className="px-5 py-3 font-semibold">Call</th>
            <th className="px-5 py-3 font-semibold">Domain</th>
            <th className="px-5 py-3 font-semibold">Status</th>
            <th className="px-5 py-3 font-semibold">Consent</th>
            <th className="px-5 py-3 font-semibold">Artifacts</th>
            <th className="px-5 py-3 font-semibold">When</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => {
            const isLive = liveId === c.call_id
            return (
              <tr key={c.call_id} onClick={() => onOpenCall(c.call_id)} className="cursor-pointer border-t border-border transition-colors hover:bg-foreground/[0.02]">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[var(--c-accent-2)]/18 text-[var(--c-accent-2)]">
                      <UserRound className="size-4" />
                    </span>
                    <div>
                      <p className="text-sm font-semibold">{titleCase(c.domain)} call</p>
                      <p className="font-mono text-xs text-muted">{shortId(c.call_id, 10)}</p>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3 text-sm capitalize">{c.domain}</td>
                <td className="px-5 py-3">
                  <Pill status={isLive ? 'live' : c.status} label={isLive ? 'Live' : titleCase(c.status)} />
                </td>
                <td className="px-5 py-3">
                  <Pill status={c.consent_granted ? 'completed' : 'declined'} label={c.consent_granted ? 'Consented' : 'No consent'} />
                </td>
                <td className="px-5 py-3">
                  <div className="flex gap-3 text-xs">
                    <span className={cn('inline-flex items-center gap-1', c.has_notes ? 'text-muted' : 'text-muted/40')}>
                      <FileText className="size-3.5" /> Notes
                    </span>
                    <span className={cn('inline-flex items-center gap-1', c.has_summary ? 'text-muted' : 'text-muted/40')}>
                      <BarChart3 className="size-3.5" /> Summary
                    </span>
                  </div>
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-sm tabular-nums text-muted">{formatRelative(c.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
