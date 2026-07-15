import { Bot, Radio, User } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'
import type { TranscriptTurnOut } from '@/lib/types'

function speakerLabel(role: string): string {
  if (role === 'assistant') return 'EchoAssist'
  if (role === 'caller') return 'Caller'
  return role || 'Unknown'
}

export function TranscriptView({
  turns,
  live,
  partial,
  pending,
}: {
  turns: TranscriptTurnOut[]
  live?: boolean
  /** A turn being produced live (caller interim STT or agent reply), shown as a typing bubble. */
  partial?: { role: string; text: string } | null
  /** The agent is working but hasn't produced text yet — show a shimmering placeholder reply. */
  pending?: boolean
}) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, partial?.text, pending])

  return (
    <div className="flex h-full flex-col rounded-2xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-muted">
          Transcript
        </h3>
        {live ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--c-accent-3)]">
            <Radio className="size-3.5 animate-pulse" />
            Live
          </span>
        ) : null}
      </div>

      <div className="max-h-[62vh] flex-1 space-y-4 overflow-y-auto p-5 scrollbar-thin">
        {turns.length === 0 && !partial && !pending ? (
          <p className="py-10 text-center text-sm text-muted">
            {live ? 'Waiting for the first turn…' : 'No transcript available.'}
          </p>
        ) : (
          turns.map((turn, index) => {
            const isAssistant = turn.role === 'assistant'
            return (
              <div
                key={`${turn.ordinal}-${index}`}
                className={cn('flex gap-3', isAssistant ? '' : 'flex-row-reverse')}
              >
                <div
                  className={cn(
                    'flex size-8 shrink-0 items-center justify-center rounded-full',
                    isAssistant ? 'bg-accent/15 text-accent' : 'bg-foreground/[0.08] text-foreground',
                  )}
                >
                  {isAssistant ? <Bot className="size-4" /> : <User className="size-4" />}
                </div>
                <div
                  className={cn(
                    'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm',
                    isAssistant ? 'bg-foreground/[0.04]' : 'bg-accent/10',
                  )}
                >
                  <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
                    {speakerLabel(turn.role)}
                  </p>
                  <p className="whitespace-pre-wrap leading-relaxed">{turn.text}</p>
                  {turn.citations && turn.citations.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {turn.citations.map((citation) => (
                        <Badge key={citation} variant="muted">
                          {citation}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            )
          })
        )}
        {partial ? (
          (() => {
            const isAssistant = partial.role === 'assistant'
            return (
              <div className={cn('flex gap-3', isAssistant ? '' : 'flex-row-reverse')}>
                <div
                  className={cn(
                    'flex size-8 shrink-0 items-center justify-center rounded-full',
                    isAssistant ? 'bg-accent/15 text-accent' : 'bg-foreground/[0.08] text-foreground',
                  )}
                >
                  {isAssistant ? <Bot className="size-4" /> : <User className="size-4" />}
                </div>
                <div
                  className={cn(
                    'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm opacity-70',
                    isAssistant ? 'bg-foreground/[0.04]' : 'bg-accent/10',
                  )}
                >
                  <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
                    {speakerLabel(partial.role)}
                  </p>
                  <p className="leading-relaxed">
                    {partial.text}
                    <span className="ml-0.5 inline-block h-4 w-px translate-y-0.5 animate-pulse bg-current" />
                  </p>
                </div>
              </div>
            )
          })()
        ) : pending ? (
          <div className="flex gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
              <Bot className="size-4" />
            </div>
            <div
              className="max-w-[80%] space-y-2 rounded-2xl bg-foreground/[0.04] px-4 py-3.5"
              aria-label="EchoAssist is preparing a reply"
            >
              <div className="h-2.5 w-44 animate-pulse rounded bg-foreground/10" />
              <div className="h-2.5 w-56 animate-pulse rounded bg-foreground/10 [animation-delay:150ms]" />
              <div className="h-2.5 w-32 animate-pulse rounded bg-foreground/10 [animation-delay:300ms]" />
            </div>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
    </div>
  )
}
