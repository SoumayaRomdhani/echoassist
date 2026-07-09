import { Loader2, PhoneCall } from 'lucide-react'
import { useState } from 'react'
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
import { ApiError } from '@/lib/api'
import { useStartCall } from '@/lib/query'

export function StartCallDialog({
  domain,
  onStarted,
}: {
  domain: string
  onStarted: (callId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [consent, setConsent] = useState(true)
  const startCall = useStartCall()

  async function handleStart() {
    try {
      const result = await startCall.mutateAsync({ domain, consent })
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
          <Button onClick={handleStart} disabled={startCall.isPending}>
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
