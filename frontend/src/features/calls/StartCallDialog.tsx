import { Loader2, PhoneCall } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/cn'
import { ApiError } from '@/lib/api'
import { useJobPostings, useStartCall } from '@/lib/query'

type Mode = 'typical' | 'tailored'

export function StartCallDialog({
  domain,
  onStarted,
}: {
  domain: string
  onStarted: (callId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [consent, setConsent] = useState(true)
  const [mode, setMode] = useState<Mode>('typical')
  const [jobPostingId, setJobPostingId] = useState<number | null>(null)
  const startCall = useStartCall()

  const { data: postings } = useJobPostings()
  const confirmed = useMemo(
    () => (postings ?? []).filter((p) => p.status === 'confirmed' && p.domain === domain),
    [postings, domain],
  )

  function chooseTailored() {
    setMode('tailored')
    // Default to the first confirmed posting so a valid choice is pre-selected.
    if (jobPostingId == null && confirmed.length > 0) setJobPostingId(confirmed[0].id)
  }

  const tailoredWithoutSelection = mode === 'tailored' && jobPostingId == null

  async function handleStart() {
    try {
      const result = await startCall.mutateAsync({
        domain,
        consent,
        ...(mode === 'tailored' && jobPostingId != null ? { job_posting_id: jobPostingId } : {}),
      })
      setOpen(false)
      toast.success('Call started', { description: 'Streaming the live transcript…' })
      onStarted(result.call_id)
    } catch (error) {
      const message = error instanceof ApiError ? error.detail : 'Could not start the call.'
      toast.error('Failed to start call', { description: message })
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="brand">
          <PhoneCall className="size-4" />
          Start call
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start a call</DialogTitle>
          <DialogDescription>
            Runs a replay-driven interview on the{' '}
            <span className="font-medium text-foreground">{domain}</span> domain and streams every
            turn live.
          </DialogDescription>
        </DialogHeader>

        {/* Interview kind: the standard flow, or a tailored one from a confirmed job posting. */}
        <div className="space-y-2">
          <Label>Interview</Label>
          <div className="grid grid-cols-2 gap-1 rounded-xl border border-border bg-background p-1">
            <ModeButton selected={mode === 'typical'} onClick={() => setMode('typical')}>
              Typical
            </ModeButton>
            <ModeButton selected={mode === 'tailored'} onClick={chooseTailored}>
              From job posting
            </ModeButton>
          </div>

          {mode === 'tailored' &&
            (confirmed.length === 0 ? (
              <p className="text-xs text-muted">
                No confirmed job postings yet. Confirm one in the{' '}
                <span className="font-medium text-foreground">Interviews</span> tab first.
              </p>
            ) : (
              <select
                aria-label="Job posting"
                value={jobPostingId ?? ''}
                onChange={(event) => setJobPostingId(Number(event.target.value))}
                className="flex h-10 w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                {confirmed.map((posting) => (
                  <option key={posting.id} value={posting.id}>
                    {posting.title} ({posting.questions.filter((q) => q.enabled).length} questions)
                  </option>
                ))}
              </select>
            ))}
        </div>

        <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-background px-4 py-3">
          <div>
            <Label htmlFor="consent-switch">Caller consents to recording</Label>
            <p className="mt-1 text-xs text-muted">
              Turn off to simulate a caller who declines — the call ends at the consent gate.
            </p>
          </div>
          <Switch id="consent-switch" checked={consent} onCheckedChange={setConsent} />
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <Button onClick={handleStart} disabled={startCall.isPending || tailoredWithoutSelection}>
            {startCall.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Starting…
              </>
            ) : (
              'Start call'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ModeButton({
  selected,
  onClick,
  children,
}: {
  selected: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
        selected
          ? 'bg-accent/15 text-foreground ring-1 ring-inset ring-accent/30'
          : 'text-muted hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}
