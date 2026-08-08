import { CheckCircle2, Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/cn'
import { ApiError } from '@/lib/api'
import { useUpdateJobPosting } from '@/lib/query'
import type { JobPostingOut, Question } from '@/lib/types'

/** A locally-editable question. `id`/`slot` are null for a freshly added one. */
type Draft = Question

function StatusBadge({ status }: { status: JobPostingOut['status'] }) {
  return status === 'confirmed' ? (
    <Badge variant="ready">
      <CheckCircle2 className="size-3" />
      confirmed
    </Badge>
  ) : (
    <Badge variant="soon">draft</Badge>
  )
}

/**
 * Review, edit, enable/disable, reorder-free add/remove of the drafted questions,
 * then Save (keep editing) or Confirm (mark ready for a tailored interview).
 * Remounted per posting via a `key`, so local edit state starts clean on switch.
 */
export function QuestionEditor({ posting }: { posting: JobPostingOut }) {
  const [title, setTitle] = useState(posting.title)
  const [questions, setQuestions] = useState<Draft[]>(posting.questions)
  const [status, setStatus] = useState(posting.status)
  const update = useUpdateJobPosting(posting.id)

  const enabledCount = questions.filter((q) => q.enabled && q.text.trim()).length

  function patchQuestion(index: number, patch: Partial<Draft>) {
    setQuestions((prev) => prev.map((q, i) => (i === index ? { ...q, ...patch } : q)))
  }

  function removeQuestion(index: number) {
    setQuestions((prev) => prev.filter((_, i) => i !== index))
  }

  function addQuestion() {
    setQuestions((prev) => [...prev, { id: null, text: '', slot: null, enabled: true }])
  }

  async function save(nextStatus?: 'confirmed') {
    const cleaned = questions.filter((q) => q.text.trim())
    try {
      const saved = await update.mutateAsync({
        title: title.trim() || posting.title,
        questions: cleaned,
        ...(nextStatus ? { status: nextStatus } : {}),
      })
      // Adopt the server's normalized set (re-ided, slugged, deduped).
      setQuestions(saved.questions)
      setTitle(saved.title)
      setStatus(saved.status)
      toast.success(nextStatus === 'confirmed' ? 'Interview ready' : 'Changes saved', {
        description:
          nextStatus === 'confirmed'
            ? 'Start a tailored interview for this role from the Calls tab.'
            : undefined,
      })
    } catch (error) {
      const message = error instanceof ApiError ? error.detail : 'Could not save the questions.'
      toast.error('Save failed', { description: message })
    }
  }

  return (
    <Card className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <Input
            aria-label="Role title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="h-9 border-transparent bg-transparent px-0 font-display text-lg font-bold shadow-none focus-visible:border-border focus-visible:bg-background focus-visible:px-3"
          />
          <p className="mt-1 text-sm text-muted">
            {enabledCount} question{enabledCount === 1 ? '' : 's'} will be asked, in order.
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      <ol className="mt-5 space-y-2">
        {questions.map((question, index) => (
          <li
            key={question.id ?? `new-${index}`}
            className={cn(
              'flex items-center gap-3 rounded-xl border border-border bg-background p-2.5',
              !question.enabled && 'opacity-60',
            )}
          >
            <Switch
              aria-label={question.enabled ? 'Disable question' : 'Enable question'}
              checked={question.enabled}
              onCheckedChange={(checked) => patchQuestion(index, { enabled: checked })}
            />
            <span className="w-5 shrink-0 text-center text-xs font-semibold tabular-nums text-muted">
              {index + 1}
            </span>
            <Input
              aria-label={`Question ${index + 1}`}
              value={question.text}
              placeholder="Type the question…"
              onChange={(event) => patchQuestion(index, { text: event.target.value })}
              className="border-transparent bg-transparent shadow-none focus-visible:border-border"
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove question ${index + 1}`}
              onClick={() => removeQuestion(index)}
            >
              <Trash2 className="text-muted" />
            </Button>
          </li>
        ))}
      </ol>

      <Button variant="subtle" size="sm" className="mt-3" onClick={addQuestion}>
        <Plus />
        Add question
      </Button>

      <div className="mt-6 flex items-center justify-end gap-2 border-t border-border pt-4">
        <Button variant="outline" onClick={() => save()} disabled={update.isPending}>
          {update.isPending ? <Loader2 className="animate-spin" /> : <Save />}
          Save changes
        </Button>
        <Button
          variant="brand"
          onClick={() => save('confirmed')}
          disabled={update.isPending || enabledCount === 0}
        >
          <CheckCircle2 />
          Confirm &amp; ready
        </Button>
      </div>
    </Card>
  )
}
