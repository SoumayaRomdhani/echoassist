import { MessageSquareText } from 'lucide-react'

export function SummaryPanel({ summary }: { summary: string | null }) {
  return (
    <section className="rounded-2xl border border-border bg-surface">
      <header className="flex items-center gap-2 border-b border-border px-5 py-3.5">
        <MessageSquareText className="size-4 text-accent" />
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-muted">
          Post-call summary
        </h3>
      </header>
      <div className="p-5">
        {summary ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{summary}</p>
        ) : (
          <p className="text-sm text-muted">The grounded summary is generated when the call ends.</p>
        )}
      </div>
    </section>
  )
}
