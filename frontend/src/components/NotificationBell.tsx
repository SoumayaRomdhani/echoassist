import { Bell, CheckCircle2, PhoneOff, XCircle, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import type { CallListOut, CallOut } from '@/lib/types'

/**
 * Self-contained notification bell for the host top bar: it polls recent calls and
 * surfaces notable outcomes (completed / failed / consent declined) as an activity feed.
 * It talks to the API through the same runtime config the agent configures on mount, so
 * it needs no query-client context. The dot lights when there is recent activity.
 */

const KIND: Record<string, { icon: LucideIcon; tone: string; text: (domain: string) => string }> = {
  completed: { icon: CheckCircle2, tone: 'text-emerald-500', text: (d) => `${cap(d)} call completed` },
  failed: { icon: XCircle, tone: 'text-[var(--c-accent-3)]', text: () => 'A call failed to finish' },
  declined: { icon: PhoneOff, tone: 'text-muted', text: () => 'Caller declined recording' },
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export function NotificationBell() {
  const [items, setItems] = useState<CallOut[]>([])

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .get<CallListOut>('/calls?limit=10')
        .then((r) => alive && setItems(r.items))
        .catch(() => {})
    void load()
    const id = setInterval(() => void load(), 15_000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const feed = items.filter((c) => c.status in KIND).slice(0, 6)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Notifications${feed.length ? ` (${feed.length})` : ''}`}
          className="relative grid size-9 place-items-center rounded-xl border border-border text-muted transition-colors hover:border-accent/40 hover:text-foreground"
        >
          {feed.length > 0 ? (
            <span className="absolute right-2 top-2 size-1.5 rounded-full bg-[var(--c-accent-3)]" />
          ) : null}
          <Bell className="size-[18px]" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Recent activity</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {feed.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-muted">No recent activity</p>
        ) : (
          <ul className="max-h-80 overflow-y-auto py-1 scrollbar-thin">
            {feed.map((c) => {
              const k = KIND[c.status]
              const Icon = k.icon
              return (
                <li key={c.call_id} className="flex items-start gap-2.5 px-2 py-2">
                  <Icon className={`mt-0.5 size-4 shrink-0 ${k.tone}`} />
                  <div className="min-w-0">
                    <p className="text-sm leading-tight">{k.text(c.domain)}</p>
                    <p className="text-xs text-muted">{formatRelative(c.created_at)}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
