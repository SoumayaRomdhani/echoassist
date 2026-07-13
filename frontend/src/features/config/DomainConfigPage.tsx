import {
  CheckCircle2,
  FileQuestion,
  ListChecks,
  MessageCircle,
  ShieldQuestion,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { useDomains } from '@/lib/query'
import type { DomainOut } from '@/lib/types'
import { DocumentUpload } from './DocumentUpload'
import { DocumentsPanel } from './DocumentsPanel'

function IndexedBadge({ indexed }: { indexed: boolean | null }) {
  if (indexed) {
    return (
      <Badge variant="ready">
        <CheckCircle2 className="size-3" />
        indexed
      </Badge>
    )
  }
  if (indexed === false) return <Badge variant="soon">empty</Badge>
  return <Badge variant="muted">unknown</Badge>
}

function Stat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-background p-3">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        <Icon className="size-3.5" />
        {label}
      </p>
      <p className="mt-1 font-display text-2xl font-bold tabular-nums">{value}</p>
    </div>
  )
}

function DomainSummary({ domain }: { domain: DomainOut }) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-bold capitalize">{domain.name}</h3>
        <Badge variant="violet">{domain.language.toUpperCase()}</Badge>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <Stat icon={FileQuestion} label="Questions" value={String(domain.question_count)} />
        <Stat icon={ListChecks} label="Slots" value={String(domain.slots.length)} />
      </div>

      <div className="mt-5 space-y-4">
        <Fact icon={MessageCircle} label="Greeting" value={domain.greeting} />
        <Fact icon={ShieldQuestion} label="AI disclosure" value={domain.disclosure} />
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Captured slots</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {domain.slots.length === 0 ? (
              <span className="text-sm text-muted">None defined.</span>
            ) : (
              domain.slots.map((slot) => (
                <Badge key={slot} variant="muted">
                  {slot}
                </Badge>
              ))
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

function Fact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        <Icon className="size-3.5" />
        {label}
      </p>
      <p className="mt-1 text-sm leading-relaxed">{value}</p>
    </div>
  )
}

export function DomainConfigPage({ defaultDomain }: { defaultDomain: string }) {
  const { data, isLoading } = useDomains()
  const [selected, setSelected] = useState(defaultDomain)

  if (isLoading) return <Skeleton className="h-72 rounded-2xl" />

  const domains = data ?? []
  const domain = domains.find((item) => item.name === selected) ?? domains[0]
  if (!domain) return <p className="text-sm text-muted">No domains are configured.</p>

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-2 lg:col-span-1">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted">Domains</p>
        {domains.map((item) => (
          <button
            key={item.name}
            type="button"
            onClick={() => setSelected(item.name)}
            className={cn(
              'flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left text-sm transition-colors',
              item.name === domain.name
                ? 'border-accent/40 bg-accent/10 text-accent'
                : 'border-border hover:bg-foreground/[0.04]',
            )}
          >
            <span className="font-medium capitalize">{item.name}</span>
            <IndexedBadge indexed={item.indexed} />
          </button>
        ))}
      </div>

      <div className="space-y-6 lg:col-span-2">
        <DomainSummary domain={domain} />
        <DocumentUpload domain={domain.name} />
        <DocumentsPanel domain={domain.name} />
      </div>
    </div>
  )
}
