import { ShieldCheck, ShieldX } from 'lucide-react'
import { Badge } from './ui/badge'

export function ConsentBadge({ granted }: { granted: boolean }) {
  return granted ? (
    <Badge variant="ready">
      <ShieldCheck className="size-3" />
      Consented
    </Badge>
  ) : (
    <Badge variant="muted">
      <ShieldX className="size-3" />
      No consent
    </Badge>
  )
}
