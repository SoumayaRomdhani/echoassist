import { ChevronsUpDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { DomainOut } from '@/lib/types'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'

/**
 * Standalone-host domain picker (NOT part of the shipped embed, which is
 * single-domain by design). Switches the whole dashboard — calls, metrics,
 * config, and start-call — between the deployment's domains, so a help-desk call
 * isn't hidden behind the screening lens.
 *
 * The list is read from the backend so nothing is hardcoded; if it can't load,
 * the active domain is still offered so the control never breaks.
 */
export function DomainSwitcher({
  value,
  onChange,
}: {
  value: string
  onChange: (domain: string) => void
}) {
  const [domains, setDomains] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    api
      .get<DomainOut[]>('/domains')
      .then((list) => {
        if (!cancelled) setDomains(list.map((item) => item.name))
      })
      .catch(() => {
        /* offline / unauthorized — fall back to just the active domain */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const options = domains.includes(value) ? domains : [value, ...domains]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Switch domain"
          className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-semibold capitalize text-foreground transition-colors hover:bg-accent/10"
        >
          {value}
          <ChevronsUpDown className="size-3.5 text-muted" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {options.map((name) => (
          <DropdownMenuItem key={name} onClick={() => onChange(name)} className="capitalize">
            {name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
