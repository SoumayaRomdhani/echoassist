import { FileText, Loader2, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ApiError } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import { useDeleteDocument, useDocuments, useReindexDomain, useSearchPreview } from '@/lib/query'
import type { DocumentInfo, RetrievedChunk } from '@/lib/types'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.detail : fallback
}

function DocumentRow({ domain, doc }: { domain: string; doc: DocumentInfo }) {
  const remove = useDeleteDocument(domain)
  async function handleDelete() {
    if (!window.confirm(`Delete "${doc.source}" and its indexed chunks? This can't be undone.`))
      return
    try {
      const report = await remove.mutateAsync(doc.source)
      toast.success('Document deleted', {
        description: `${report.filename}: ${report.chunks_removed} chunks purged`,
      })
    } catch (error) {
      toast.error('Delete failed', { description: errorMessage(error, 'Delete failed.') })
    }
  }

  return (
    <TableRow>
      <TableCell className="font-medium">
        <span className="flex items-center gap-2">
          <FileText className="size-4 shrink-0 text-muted" />
          {doc.source}
        </span>
      </TableCell>
      <TableCell className="tabular-nums text-muted">{formatBytes(doc.size_bytes)}</TableCell>
      <TableCell className="tabular-nums text-muted">{doc.chunks ?? '—'}</TableCell>
      <TableCell className="text-muted">{formatRelative(doc.modified_at)}</TableCell>
      <TableCell className="text-right">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleDelete}
          disabled={remove.isPending}
          aria-label={`Delete ${doc.source}`}
        >
          {remove.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Trash2 className="size-4 text-[var(--c-accent-3)]" />
          )}
        </Button>
      </TableCell>
    </TableRow>
  )
}

function ResultCard({ chunk }: { chunk: RetrievedChunk }) {
  return (
    <div className="rounded-xl border border-border bg-background p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="muted">{chunk.source}</Badge>
        {chunk.page != null ? <Badge variant="muted">p{chunk.page}</Badge> : null}
        {chunk.heading ? <span className="text-muted">{chunk.heading}</span> : null}
        <span className="ml-auto tabular-nums text-muted">score {chunk.score.toFixed(3)}</span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-foreground/80">{chunk.snippet}…</p>
    </div>
  )
}

function SearchPreview({ domain }: { domain: string }) {
  const [query, setQuery] = useState('')
  const search = useSearchPreview(domain)

  async function handleSearch() {
    const q = query.trim()
    if (!q) return
    try {
      await search.mutateAsync(q)
    } catch (error) {
      toast.error('Search failed', { description: errorMessage(error, 'Search failed.') })
    }
  }

  const results = search.data?.results ?? []
  return (
    <div className="mt-6 border-t border-border pt-5">
      <p className="font-display text-sm font-semibold">Preview retrieval</p>
      <p className="mt-1 text-xs text-muted">
        Ask a test question to see exactly which chunks the agent would ground on.
      </p>
      <div className="mt-3 flex gap-2">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && handleSearch()}
          placeholder="e.g. how do I reset my password?"
        />
        <Button onClick={handleSearch} disabled={search.isPending || query.trim().length === 0}>
          {search.isPending ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
          Search
        </Button>
      </div>
      {search.isSuccess && results.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No chunks retrieved for that query.</p>
      ) : null}
      {results.length > 0 ? (
        <div className="mt-3 space-y-2">
          {results.map((chunk, i) => (
            <ResultCard key={`${chunk.source}-${i}`} chunk={chunk} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function DocumentsPanel({ domain }: { domain: string }) {
  const { data, isLoading } = useDocuments(domain)
  const reindex = useReindexDomain(domain)
  const documents = data?.documents ?? []

  async function handleReindex() {
    try {
      const report = await reindex.mutateAsync()
      toast.success('Domain reindexed', {
        description: `${report.documents} docs · ${report.chunks} chunks${
          report.skipped?.length ? ` · ${report.skipped.length} skipped` : ''
        }`,
      })
    } catch (error) {
      toast.error('Reindex failed', { description: errorMessage(error, 'Reindex failed.') })
    }
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-bold">Knowledge base</h3>
        <Button variant="outline" size="sm" onClick={handleReindex} disabled={reindex.isPending}>
          {reindex.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <RefreshCw className="size-4" />
          )}
          Reindex
        </Button>
      </div>

      <div className="mt-4">
        {isLoading ? (
          <Skeleton className="h-24 rounded-xl" />
        ) : documents.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted">
            No documents yet. Upload one above to build this domain's knowledge base.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Document</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Modified</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <DocumentRow key={doc.source} domain={domain} doc={doc} />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <SearchPreview domain={domain} />
    </Card>
  )
}
