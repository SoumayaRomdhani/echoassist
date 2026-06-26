import {
  CheckCircle2,
  Loader2,
  PhoneCall,
  PhoneOff,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { Badge, type BadgeProps } from './ui/badge'
import type { CallStatus } from '@/lib/types'

const STATUS: Record<
  CallStatus,
  { label: string; variant: BadgeProps['variant']; icon: LucideIcon; spin?: boolean }
> = {
  started: { label: 'Started', variant: 'default', icon: PhoneCall },
  interviewing: { label: 'Interviewing', variant: 'violet', icon: Loader2, spin: true },
  completed: { label: 'Completed', variant: 'ready', icon: CheckCircle2 },
  declined: { label: 'Declined', variant: 'muted', icon: PhoneOff },
  failed: { label: 'Failed', variant: 'pink', icon: XCircle },
}

export function StatusBadge({ status }: { status: CallStatus }) {
  const config = STATUS[status] ?? STATUS.started
  const Icon = config.icon
  return (
    <Badge variant={config.variant}>
      <Icon className={config.spin ? 'size-3 animate-spin' : 'size-3'} />
      {config.label}
    </Badge>
  )
}
