import { ShieldCheck } from 'lucide-react'
import { useConsentLog } from '@/lib/query'
import { formatDateTime, shortId } from '@/lib/format'

export function ConsentPanel({ callId }: { callId: string }) {
  const { data, isLoading } = useConsentLog(callId)
  const entries = data ?? []

  return (
    <section className="rounded-2xl border border-border bg-surface">
      <header className="flex items-center gap-2 border-b border-border px-5 py-3.5">
        <ShieldCheck className="size-4 text-accent" />
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-muted">
          Consent audit trail
        </h3>
      </header>
      <div className="p-5 text-sm">
        {isLoading ? (
          <p className="text-muted">Loading…</p>
        ) : entries.length === 0 ? (
          <p className="text-muted">No consent record yet.</p>
        ) : (
          <ul className="space-y-3">
            {entries.map((entry, index) => (
              <li
                key={`${entry.created_at}-${index}`}
                className="rounded-xl border border-border bg-background p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium capitalize">{entry.decision}</span>
                  <span
                    className={entry.granted ? 'text-emerald-500' : 'text-[var(--c-accent-3)]'}
                  >
                    {entry.granted ? 'granted' : 'not granted'}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted">{formatDateTime(entry.created_at)}</p>
                {entry.disclosure_hash ? (
                  <p className="mt-1 break-all font-mono text-[11px] text-muted">
                    disclosure&nbsp;{shortId(entry.disclosure_hash, 18)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
