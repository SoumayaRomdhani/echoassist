import { LogOut } from 'lucide-react'
import type { ReactNode } from 'react'
import { useAuth } from '@/auth/AuthProvider'
import { BrandMark } from './BrandMark'
import { ReadinessIndicator } from './ReadinessIndicator'
import { ThemeToggle } from './ThemeToggle'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'

/**
 * Minimal branded app frame for the STANDALONE host (not shipped to ACTEEK).
 * A slim top bar — EchoAssist brand, backend health, theme, and the signed-in
 * user menu — wrapping the embeddable agent. It is deliberately not a marketplace.
 */
export function AppFrame({
  children,
  headerSlot,
}: {
  children: ReactNode
  /** Optional control rendered in the top bar (e.g. the domain switcher). */
  headerSlot?: ReactNode
}) {
  const { user, signOut } = useAuth()
  const initial = (user?.name?.[0] ?? 'M').toUpperCase()

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-2.5">
            <BrandMark className="size-7" />
            <span className="font-display text-lg font-bold">EchoAssist</span>
            <span className="rounded-full border border-border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-muted">
              ACTEEK
            </span>
          </div>

          <div className="flex items-center gap-3">
            {headerSlot}
            <ReadinessIndicator />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label="Account menu"
                  className="flex size-9 items-center justify-center rounded-full bg-accent/15 font-display text-sm font-bold text-accent ring-1 ring-accent/20 transition-colors hover:bg-accent/25"
                >
                  {initial}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuLabel>
                  <span className="block font-semibold text-foreground">{user?.name ?? 'MVP'}</span>
                  <span className="block font-normal text-muted">
                    {user?.email ?? 'mvp@acteek.com'}
                  </span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={signOut}>
                  <LogOut className="size-4" />
                  Log out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <main>{children}</main>
    </div>
  )
}
