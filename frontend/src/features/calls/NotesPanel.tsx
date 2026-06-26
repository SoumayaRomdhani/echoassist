import { FileText } from 'lucide-react'
import { titleCase } from '@/lib/format'

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length > 0 ? value.map(String).join(', ') : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function NotesPanel({ notes }: { notes: Record<string, unknown> | null }) {
  const entries = notes ? Object.entries(notes) : []

  return (
    <section className="rounded-2xl border border-border bg-surface">
      <header className="flex items-center gap-2 border-b border-border px-5 py-3.5">
        <FileText className="size-4 text-accent" />
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-muted">
          Structured notes
        </h3>
      </header>
      <div className="p-5">
        {entries.length === 0 ? (
          <p className="text-sm text-muted">Notes are extracted when the call ends.</p>
        ) : (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            {entries.map(([key, value]) => (
              <div key={key}>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
                  {titleCase(key)}
                </dt>
                <dd className="mt-0.5 text-sm">{renderValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </section>
  )
}
