import { AlertTriangle, FileText, Plus } from 'lucide-react'
import { useState } from 'react'
import { EmptyState } from '@/components/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { ApiError } from '@/lib/api'
import { useJobPosting, useJobPostings } from '@/lib/query'
import { NewJobPostingForm } from './NewJobPostingForm'
import { QuestionEditor } from './QuestionEditor'

/**
 * Interviews-from-job-description: the recruiter pastes a job description, the
 * agent drafts screening questions, and the recruiter reviews/edits/confirms
 * them here. A confirmed posting can then drive a tailored interview (Calls tab).
 */
export function JobPostingsTab({ domain }: { domain: string }) {
  const { data, isLoading, isError, error } = useJobPostings()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)

  const postings = data ?? []

  function startCreating() {
    setCreating(true)
    setSelectedId(null)
  }

  function select(id: number) {
    setSelectedId(id)
    setCreating(false)
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-semibold">Interviews from a job description</h2>
          <p className="text-sm text-muted">
            Draft screening questions from a job posting, confirm them, and run a tailored interview.
          </p>
        </div>
        <Button variant="brand" onClick={startCreating}>
          <Plus />
          New job posting
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-72 rounded-2xl" />
      ) : isError ? (
        <PostingsError error={error} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-2 lg:col-span-1">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted">
              Job postings
            </p>
            {postings.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-muted">
                No job postings yet. Create one to draft interview questions.
              </p>
            ) : (
              postings.map((posting) => {
                const enabled = posting.questions.filter((q) => q.enabled).length
                return (
                  <button
                    key={posting.id}
                    type="button"
                    onClick={() => select(posting.id)}
                    className={cn(
                      'flex w-full items-start justify-between gap-2 rounded-xl border px-4 py-3 text-left text-sm transition-colors',
                      posting.id === selectedId && !creating
                        ? 'border-accent/40 bg-accent/10'
                        : 'border-border hover:bg-foreground/[0.04]',
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{posting.title}</span>
                      <span className="text-xs text-muted">{enabled} questions</span>
                    </span>
                    <Badge variant={posting.status === 'confirmed' ? 'ready' : 'soon'}>
                      {posting.status}
                    </Badge>
                  </button>
                )
              })
            )}
          </div>

          <div className="lg:col-span-2">
            {creating ? (
              <NewJobPostingForm
                domain={domain}
                onCreated={(posting) => select(posting.id)}
                onCancel={() => setCreating(false)}
              />
            ) : selectedId != null ? (
              <SelectedPosting id={selectedId} onDeleted={() => setSelectedId(null)} />
            ) : (
              <EmptyState
                icon={FileText}
                title="Select or create a job posting"
                description="Pick a posting to review its questions, or create a new one from a job description."
                action={
                  <Button variant="brand" onClick={startCreating}>
                    <Plus />
                    New job posting
                  </Button>
                }
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SelectedPosting({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { data, isLoading, isError } = useJobPosting(id)
  if (isLoading) return <Skeleton className="h-72 rounded-2xl" />
  if (isError || !data) return <PostingsError error={undefined} />
  // key -> remount on switch so QuestionEditor's local edit state resets cleanly.
  return <QuestionEditor key={data.id} posting={data} onDeleted={onDeleted} />
}

function PostingsError({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.status === 0
        ? 'Cannot reach the backend.'
        : error.detail
      : 'Something went wrong.'
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load job postings"
      description={`${message} Check that the API is running, or set VITE_USE_MOCKS=true for the in-browser demo.`}
    />
  )
}
