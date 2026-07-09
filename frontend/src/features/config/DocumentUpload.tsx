import { Loader2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { useUploadDocument } from '@/lib/query'

export function DocumentUpload({ domain }: { domain: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const upload = useUploadDocument(domain)

  async function handleFile(file: File | undefined) {
    if (!file) return
    setFileName(file.name)
    try {
      const report = await upload.mutateAsync(file)
      toast.success('Document indexed', {
        description: `${report.filename}: ${report.chunks} chunks · ${report.collection_count} in collection`,
      })
    } catch (error) {
      const message = error instanceof ApiError ? error.detail : 'Upload failed.'
      toast.error('Upload failed', { description: message })
    } finally {
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="rounded-2xl border border-dashed border-border bg-surface p-6 text-center">
      <Upload className="mx-auto size-8 text-muted" />
      <p className="mt-3 font-display text-sm font-semibold">
        Add a document to the knowledge base
      </p>
      <p className="mt-1 text-xs text-muted">
        Markdown, plain text, PDF, Word (.docx), or HTML. The domain collection re-indexes
        immediately.
      </p>
      <input
        ref={inputRef}
        type="file"
        accept=".md,.markdown,.txt,.pdf,.docx,.html,.htm,text/markdown,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/html"
        className="hidden"
        onChange={(event) => handleFile(event.target.files?.[0])}
      />
      <Button
        className="mt-4"
        variant="outline"
        onClick={() => inputRef.current?.click()}
        disabled={upload.isPending}
      >
        {upload.isPending ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            Indexing {fileName}…
          </>
        ) : (
          <>
            <Upload className="size-4" />
            Choose file
          </>
        )}
      </Button>
    </div>
  )
}
