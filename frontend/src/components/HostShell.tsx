import {
  BarChart3,
  LayoutGrid,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  PhoneCall,
  Search,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { useAuth } from '@/auth/AuthProvider'
import type { AgentSection } from '@/embed/types'
import { cn } from '@/lib/cn'
import { titleCase } from '@/lib/format'
import { BrandMark } from './BrandMark'
import { NotificationBell } from './NotificationBell'
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
  domain,
  domainSlot,
  searchValue = '',
  onSearch,
  children,
}: {
  section: AgentSection
  onSection: (section: AgentSection) => void
  /** The active domain, shown in the top-bar breadcrumb. */
  domain?: string
  domainSlot?: ReactNode
  searchValue?: string
  onSearch?: (value: string) => void
  children: ReactNode
}) {
  const { user, signOut } = useAuth()
  const initial = (user?.name?.[0] ?? 'M').toUpperCase()

  // SaaS-style collapse: narrows the sidebar to an icon rail; persisted so it
  // survives a refresh. Applies at md+ only (below md the sidebar is hidden and
  // the bottom nav takes over).
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== 'undefined' && localStorage.getItem('echo.sidebar.collapsed') === '1',
  )
  useEffect(() => {
    localStorage.setItem('echo.sidebar.collapsed', collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div
      className={cn(
        'grid h-screen grid-cols-1 overflow-hidden bg-background text-foreground',
        'md:transition-[grid-template-columns] md:duration-300 md:ease-in-out',
        collapsed ? 'md:grid-cols-[76px_1fr]' : 'md:grid-cols-[248px_1fr]',
      )}
    >
      {/* Sidebar — deliberately always dark, for brand consistency across themes. It stays
          fixed to the viewport (the shell doesn't scroll); only the main content does. */}
      <aside
        className={cn(
          'hidden h-screen flex-col gap-7 overflow-y-auto overflow-x-hidden border-r border-[rgba(99,179,237,0.14)] bg-[#0A0C10] py-6 text-[#E8EEFF] scrollbar-thin md:flex',
          collapsed ? 'items-center px-3' : 'px-4',
        )}
      >
        <div className={cn('flex items-center gap-2.5', collapsed ? 'px-0' : 'px-2')}>
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#4AF4FF] to-[#7C6BFF] shadow-[0_0_22px_rgba(74,244,255,0.28)]">
            <BrandMark className="size-5" />
          </span>
          {!collapsed && (
            <span className="leading-tight">
              <span className="block font-display text-[15px] font-bold">EchoAssist</span>
              <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-[#7E93BC]">
                by ACTEEK
              </span>
            </span>
          )}
        </div>

        {/* Collapse / expand toggle. */}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-pressed={collapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={cn(
            '-mt-3 flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-[#8FA6D4] transition-colors hover:bg-[rgba(99,179,237,0.07)] hover:text-[#E8EEFF]',
            collapsed && 'justify-center px-0',
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-[18px]" />
          ) : (
            <PanelLeftClose className="size-[18px]" />
          )}
          {!collapsed && <span className="whitespace-nowrap">Collapse</span>}
        </button>

        <nav className="flex w-full flex-col gap-4">
          {GROUPS.map((group, gi) => (
            <div
              key={group.label}
              className={cn(
                'flex flex-col gap-1',
                collapsed && gi > 0 && 'mt-1 border-t border-[rgba(99,179,237,0.14)] pt-3',
              )}
            >
              {!collapsed && (
                <p className="px-3 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-[#566789]">
                  {group.label}
                </p>
              )}
              {group.items.map(({ key, label, icon: Icon }) => {
                const active = section === key
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => onSection(key)}
                    aria-current={active ? 'page' : undefined}
                    title={collapsed ? label : undefined}
                    className={cn(
                      'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                      collapsed && 'justify-center px-0',
                      active
                        ? 'bg-gradient-to-r from-[#4AF4FF] to-[#6AD9FF] font-semibold text-[#06121A] shadow-[0_6px_20px_rgba(74,244,255,0.22)]'
                        : 'text-[#8FA6D4] hover:bg-[rgba(99,179,237,0.07)] hover:text-[#E8EEFF]',
                    )}
                  >
                    <Icon className="size-[18px] shrink-0" />
                    {!collapsed && <span className="whitespace-nowrap">{label}</span>}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div
          className={cn(
            'mt-auto flex items-center rounded-xl border border-[rgba(99,179,237,0.14)]',
            collapsed ? 'flex-col gap-2 p-2' : 'gap-3 p-2.5',
          )}
        >
          <span
            title={collapsed ? (user?.name ?? 'MVP') : undefined}
            className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#7C6BFF] to-[#4AF4FF] text-xs font-bold text-[#06121A]"
          >
            {initial}
          </span>
          {!collapsed && (
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[13px] font-semibold">{user?.name ?? 'MVP'}</span>
              <span className="block truncate text-[11px] text-[#7E93BC]">
                {user?.email ?? 'mvp@acteek.com'}
              </span>
            </span>
          )}
          <button
            type="button"
            onClick={signOut}
            aria-label="Log out"
            title={collapsed ? 'Log out' : undefined}
            className="grid size-8 shrink-0 place-items-center rounded-lg text-[#8FA6D4] transition-colors hover:bg-[rgba(99,179,237,0.08)] hover:text-[#E8EEFF]"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      {/* Main — its own column; only <main> scrolls, so the top bar + sidebar stay fixed. */}
      <div className="flex min-w-0 flex-col overflow-hidden">
        <header className="z-40 flex shrink-0 items-center gap-4 border-b border-border bg-background/80 px-5 py-3.5 backdrop-blur md:px-8">
          {/* Mobile brand (sidebar is hidden below md) */}
          <div className="flex items-center gap-2 md:hidden">
            <BrandMark className="size-6" />
          </div>
          <h1 className="shrink-0 font-display text-xl font-semibold">
            {TITLE[section]}
            {domain ? <span className="ml-1 font-medium text-muted">· {titleCase(domain)}</span> : null}
          </h1>
          <label className="hidden min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-foreground/[0.03] px-3.5 py-2 text-muted focus-within:border-accent/40 lg:flex lg:max-w-sm">
            <Search className="size-4 shrink-0" />
            <input
              type="search"
              value={searchValue}
              onChange={(e) => onSearch?.(e.target.value)}
              placeholder="Search calls by id, domain, or status…"
              className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted"
            />
          </label>
          <div className="ml-auto flex items-center gap-2.5">
            {domainSlot}
            <NotificationBell />
            <ReadinessIndicator />
            <ThemeToggle />
            <span className="grid size-9 place-items-center rounded-full bg-accent/15 font-display text-sm font-bold text-accent ring-1 ring-accent/20">
              {initial}
            </span>
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">{children}</main>

        {/* Mobile nav — the sidebar hides below md, so keep the sections reachable. */}
        <nav className="z-40 flex shrink-0 border-t border-border bg-background/90 backdrop-blur md:hidden">
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
