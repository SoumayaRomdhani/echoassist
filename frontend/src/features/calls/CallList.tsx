import { FileText, MessageSquareText, PhoneCall } from 'lucide-react'
import type { ReactNode } from 'react'
import { ConsentBadge } from '@/components/ConsentBadge'
import { EmptyState } from '@/components/EmptyState'
import { StatusBadge } from '@/components/StatusBadge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/cn'
import { formatDateTime, shortId } from '@/lib/format'
import type { CallOut } from '@/lib/types'

export function CallList({
  calls,
  emptyAction,
  onSelect,
}: {
  calls: CallOut[]
  emptyAction?: ReactNode
  onSelect: (callId: string) => void
}) {
  if (calls.length === 0) {
    return (
      <EmptyState
        icon={PhoneCall}
        title="No calls yet"
        description="Start a screening call to see it here with a live transcript, structured notes, and a faithful post-call summary."
        action={emptyAction}
      />
    )
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Call</TableHead>
            <TableHead>Started</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Consent</TableHead>
            <TableHead>Artifacts</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {calls.map((call) => (
            <TableRow
              key={call.call_id}
              className="cursor-pointer"
              onClick={() => onSelect(call.call_id)}
            >
              <TableCell className="font-mono text-xs text-muted">{shortId(call.call_id)}</TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                {formatDateTime(call.created_at)}
              </TableCell>
              <TableCell>
                <StatusBadge status={call.status} />
              </TableCell>
              <TableCell>
                <ConsentBadge granted={call.consent_granted} />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-3 text-xs">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1',
                      call.has_notes ? 'text-foreground' : 'text-muted/50',
                    )}
                  >
                    <FileText className="size-3.5" />
                    Notes
                  </span>
                  <span
                    className={cn(
                      'inline-flex items-center gap-1',
                      call.has_summary ? 'text-foreground' : 'text-muted/50',
                    )}
                  >
                    <MessageSquareText className="size-3.5" />
                    Summary
                  </span>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
