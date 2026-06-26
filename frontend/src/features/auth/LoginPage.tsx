import { Loader2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { toast } from 'sonner'
import { useAuth } from '@/auth/AuthProvider'
import { signInWithPassword, signInWithSso, type AuthSession, type SsoProvider } from '@/auth/sso'
import { BrandMark } from '@/components/BrandMark'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Pending = SsoProvider | 'password' | null

function MicrosoftGlyph() {
  return (
    <svg viewBox="0 0 21 21" className="size-4" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  )
}

function GoogleGlyph() {
  return (
    <svg viewBox="0 0 48 48" className="size-4" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8a12 12 0 1 1 7.9-21l5.7-5.7A20 20 0 1 0 24 44c11 0 20-8 20-20 0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8A12 12 0 0 1 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7A20 20 0 0 0 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2A12 12 0 0 1 12.7 28l-6.5 5A20 20 0 0 0 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H24v8h11.3a12 12 0 0 1-4.1 5.6l6.2 5.2C40.9 36.3 44 30.7 44 24c0-1.2-.1-2.3-.4-3.5z" />
    </svg>
  )
}

function GithubGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden="true">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.79 2.73 1.27 3.4.97.1-.76.41-1.27.74-1.56-2.56-.29-5.26-1.28-5.26-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.7 5.41-5.27 5.69.42.36.8 1.08.8 2.18v3.23c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  )
}

export function LoginPage() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState<Pending>(null)

  async function complete(which: Pending, run: () => Promise<AuthSession>) {
    setPending(which)
    try {
      signIn(await run())
    } catch {
      toast.error('Sign-in failed', { description: 'Please try again.' })
      setPending(null)
    }
  }

  function onPasswordSubmit(event: FormEvent) {
    event.preventDefault()
    const address = email.trim() || 'mvp@acteek.com'
    void complete('password', () => signInWithPassword(address))
  }

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-[#05070f] px-4 py-10">
      {/* Ambient neon + dotted-grid backdrop (ARCHITECTURE.md §8). */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(1100px 520px at 12% 8%, rgba(74,244,255,0.18), transparent 60%), radial-gradient(1100px 520px at 88% 92%, rgba(124,107,255,0.20), transparent 60%), linear-gradient(160deg, #05070f, #0c1230 120%)',
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.22]"
        style={{
          backgroundImage: 'radial-gradient(rgba(99,179,237,0.30) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 flex size-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] shadow-lg backdrop-blur">
            <BrandMark className="size-8" />
          </div>
          <h1 className="font-display text-2xl font-bold text-[#E8EEFF]">EchoAssist</h1>
          <p className="mt-1 text-sm text-[#C4D8FF]/70">Autonomous voice screening · ACTEEK</p>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#0b0f1d]/85 p-7 text-[#E8EEFF] shadow-2xl backdrop-blur-xl">
          <h2 className="font-display text-lg font-semibold">Log in to your account</h2>
          <p className="mt-1 text-sm text-[#C4D8FF]/70">Use ACTEEK SSO or your work email.</p>

          <form onSubmit={onPasswordSubmit} className="mt-5 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-[#C4D8FF]">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@acteek.com"
                className="border-white/15 bg-white/5 text-[#E8EEFF] placeholder:text-[#C4D8FF]/40"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-[#C4D8FF]">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
                className="border-white/15 bg-white/5 text-[#E8EEFF] placeholder:text-[#C4D8FF]/40"
              />
            </div>
            <Button type="submit" variant="brand" className="w-full" disabled={pending !== null}>
              {pending === 'password' ? <Loader2 className="size-4 animate-spin" /> : 'Log in'}
            </Button>
          </form>

          <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-widest text-[#C4D8FF]/40">
            <span className="h-px flex-1 bg-white/10" />
            or
            <span className="h-px flex-1 bg-white/10" />
          </div>

          <div className="space-y-2.5">
            <SsoButton
              label="Continue with Microsoft"
              glyph={<MicrosoftGlyph />}
              pending={pending === 'microsoft'}
              disabled={pending !== null}
              onClick={() => void complete('microsoft', () => signInWithSso('microsoft'))}
            />
            <SsoButton
              label="Continue with Google"
              glyph={<GoogleGlyph />}
              pending={pending === 'google'}
              disabled={pending !== null}
              onClick={() => void complete('google', () => signInWithSso('google'))}
            />
            <SsoButton
              label="Continue with GitHub"
              glyph={<GithubGlyph />}
              pending={pending === 'github'}
              disabled={pending !== null}
              onClick={() => void complete('github', () => signInWithSso('github'))}
            />
          </div>
        </div>

        <p className="mt-5 text-center text-[11px] text-[#C4D8FF]/50">
          Dev SSO stub — ACTEEK's identity provider plugs in here.
        </p>
      </div>
    </div>
  )
}

function SsoButton({
  label,
  glyph,
  pending,
  disabled,
  onClick,
}: {
  label: string
  glyph: ReactNode
  pending: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center justify-center gap-2.5 rounded-lg border border-white/12 bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-[#E8EEFF] transition-colors hover:bg-white/[0.09] disabled:opacity-50"
    >
      {pending ? <Loader2 className="size-4 animate-spin" /> : glyph}
      {label}
    </button>
  )
}
