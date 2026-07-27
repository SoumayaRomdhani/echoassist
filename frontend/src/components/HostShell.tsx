import {
  BarChart3,
  Bell,
  LayoutGrid,
  LogOut,
  PhoneCall,
  Search,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useAuth } from '@/auth/AuthProvider'
import type { AgentSection } from '@/embed/types'
import { cn } from '@/lib/cn'
import { BrandMark } from './BrandMark'
import { ReadinessIndicator } from './ReadinessIndicator'
import { ThemeToggle } from './ThemeToggle'

/**
 * SaaS shell for the STANDALONE host (not shipped to ACTEEK): a permanent, always-dark
 * sidebar carrying ACTEEK's brand identity + the workspace nav, a slim top bar, and the
 * embedded agent in the content area. It owns no data — the sidebar simply drives which
 * section the agent renders. ACTEEK's own marketplace shell replaces this in production.
 */

type NavItem = { key: AgentSection; label: string; icon: LucideIcon }
const NAV: NavItem[] = [
  { key: 'overview', label: 'Overview', icon: LayoutGrid },
  { key: 'calls', label: 'Calls', icon: PhoneCall },
  { key: 'metrics', label: 'Metrics', icon: BarChart3 },
  { key: 'config', label: 'Configuration', icon: SlidersHorizontal },
]
const GROUPS: { label: string; items: NavItem[] }[] = [
  { label: 'Workspace', items: NAV.slice(0, 3) },
  { label: 'Agent', items: NAV.slice(3) },
]

const TITLE: Record<AgentSection, string> = {
  overview: 'Overview',
  calls: 'Calls',
  metrics: 'Metrics',
  config: 'Configuration',
}

export function HostShell({
  section,
  onSection,
  domainSlot,
  children,
}: {
  section: AgentSection
  onSection: (section: AgentSection) => void
  domainSlot?: ReactNode
  children: ReactNode
}) {
  const { user, signOut } = useAuth()
  const initial = (user?.name?.[0] ?? 'M').toUpperCase()

  return (
    <div className="grid min-h-screen grid-cols-1 bg-background text-foreground md:grid-cols-[248px_1fr]">
      {/* Sidebar — deliberately always dark, for brand consistency across themes. */}
      <aside className="hidden flex-col gap-7 border-r border-[rgba(99,179,237,0.14)] bg-[#0A0C10] px-4 py-6 text-[#E8EEFF] md:flex">
        <div className="flex items-center gap-2.5 px-2">
          <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-[#4AF4FF] to-[#7C6BFF] shadow-[0_0_22px_rgba(74,244,255,0.28)]">
            <BrandMark className="size-5" />
          </span>
          <span className="leading-tight">
            <span className="block font-display text-[15px] font-bold">EchoAssist</span>
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-[#7E93BC]">
              by ACTEEK
            </span>
          </span>
        </div>

        <nav className="flex flex-col gap-4">
          {GROUPS.map((group) => (
            <div key={group.label} className="flex flex-col gap-1">
              <p className="px-3 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-[#566789]">
                {group.label}
              </p>
              {group.items.map(({ key, label, icon: Icon }) => {
                const active = section === key
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => onSection(key)}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                      active
                        ? 'bg-gradient-to-r from-[#4AF4FF] to-[#6AD9FF] font-semibold text-[#06121A] shadow-[0_6px_20px_rgba(74,244,255,0.22)]'
                        : 'text-[#8FA6D4] hover:bg-[rgba(99,179,237,0.07)] hover:text-[#E8EEFF]',
                    )}
                  >
                    <Icon className="size-[18px]" />
                    {label}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="mt-auto flex items-center gap-3 rounded-xl border border-[rgba(99,179,237,0.14)] p-2.5">
          <span className="grid size-8 place-items-center rounded-full bg-gradient-to-br from-[#7C6BFF] to-[#4AF4FF] text-xs font-bold text-[#06121A]">
            {initial}
          </span>
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-[13px] font-semibold">{user?.name ?? 'MVP'}</span>
            <span className="block truncate text-[11px] text-[#7E93BC]">
              {user?.email ?? 'mvp@acteek.com'}
            </span>
          </span>
          <button
            type="button"
            onClick={signOut}
            aria-label="Log out"
            className="grid size-8 shrink-0 place-items-center rounded-lg text-[#8FA6D4] transition-colors hover:bg-[rgba(99,179,237,0.08)] hover:text-[#E8EEFF]"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-40 flex items-center gap-4 border-b border-border bg-background/80 px-5 py-3.5 backdrop-blur md:px-8">
          {/* Mobile brand (sidebar is hidden below md) */}
          <div className="flex items-center gap-2 md:hidden">
            <BrandMark className="size-6" />
          </div>
          <h1 className="shrink-0 font-display text-xl font-semibold">
            {TITLE[section]}
            <span className="ml-1 font-medium text-muted">· Screening</span>
          </h1>
          <label className="hidden min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-foreground/[0.03] px-3.5 py-2 text-muted focus-within:border-accent/40 lg:flex lg:max-w-sm">
            <Search className="size-4 shrink-0" />
            <input
              type="search"
              placeholder="Search calls, candidates, sources…"
              className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted"
            />
          </label>
          <div className="ml-auto flex items-center gap-2.5">
            {domainSlot}
            <button
              type="button"
              aria-label="Notifications"
              className="relative grid size-9 place-items-center rounded-xl border border-border text-muted transition-colors hover:border-accent/40 hover:text-foreground"
            >
              <span className="absolute right-2 top-2 size-1.5 rounded-full bg-[var(--c-accent-3)]" />
              <Bell className="size-[18px]" />
            </button>
            <ReadinessIndicator />
            <ThemeToggle />
            <span className="grid size-9 place-items-center rounded-full bg-accent/15 font-display text-sm font-bold text-accent ring-1 ring-accent/20">
              {initial}
            </span>
          </div>
        </header>

        <main className="min-w-0 flex-1">{children}</main>

        {/* Mobile nav — the sidebar hides below md, so keep the sections reachable. */}
        <nav className="sticky bottom-0 z-40 flex border-t border-border bg-background/90 backdrop-blur md:hidden">
          {NAV.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onSection(key)}
              className={cn(
                'flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium',
                section === key ? 'text-accent' : 'text-muted',
              )}
            >
              <Icon className="size-5" />
              {label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  )
}
