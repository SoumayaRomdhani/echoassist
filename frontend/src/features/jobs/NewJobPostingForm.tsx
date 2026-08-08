import { Loader2, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { useCreateJobPosting } from '@/lib/query'
import type { JobPostingOut } from '@/lib/types'

/**
 * Paste a job description (fiche de poste) and let the agent draft screening
 * questions from it. On success the new draft posting is selected for review.
 */
export function NewJobPostingForm({
  domain,
  onCreated,
  onCancel,
}: {
  domain: string
  onCreated: (posting: JobPostingOut) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const create = useCreateJobPosting()

  const canGenerate = title.trim().length > 0 && description.trim().length > 0

  async function handleGenerate() {
    try {
      const posting = await create.mutateAsync({ title: title.trim(), description: description.trim(), domain })
      toast.success('Questions drafted', {
        description: 'Review, edit, and confirm them below.',
      })
      onCreated(posting)
    } catch (error) {
      const message = error instanceof ApiError ? error.detail : 'Could not generate questions.'
      toast.error('Generation failed', { description: message })
    }
  }

  return (
    <Card className="p-6">
      <h3 className="font-display text-lg font-bold">New job posting</h3>
      <p className="mt-1 text-sm text-muted">
        The agent drafts screening questions from the description. You confirm or edit them, then
        run a tailored interview.
      </p>

      <div className="mt-5 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="jp-title">Role title</Label>
          <Input
            id="jp-title"
            placeholder="e.g. Senior Backend Engineer"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="jp-description">Job description</Label>
          <textarea
            id="jp-description"
            rows={9}
            placeholder="Paste the job description here — responsibilities, required skills, stack, seniority…"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="flex w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground shadow-sm transition-colors placeholder:text-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
      </div>

      <div className="mt-5 flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onCancel} disabled={create.isPending}>
          Cancel
        </Button>
        <Button variant="brand" onClick={handleGenerate} disabled={!canGenerate || create.isPending}>
          {create.isPending ? (
            <>
              <Loader2 className="animate-spin" />
              Drafting…
            </>
          ) : (
            <>
              <Wand2 />
              Generate questions
            </>
          )}
        </Button>
      </div>
    </Card>
  )
}
