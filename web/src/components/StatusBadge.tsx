import type { LucideIcon } from 'lucide-react'
import { CircleDashed, CircleHelp, Diff, Equal, FlaskConical, Unlink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TONE_CLASSES, type Tone } from '@/lib/tones'
import { cn } from '@/lib/utils'

/**
 * What running the code showed. Where a function sits (your change, or code that calls it)
 * is a separate question, drawn as the map box's outline rather than a status.
 */
export type EvidenceStatus = 'behavior_differs' | 'inconclusive' | 'needs_probe' | 'same' | 'not_run' | 'unknown_edge'

export const STATUS_META: Record<EvidenceStatus, { label: string; icon: LucideIcon; tone: Tone }> = {
  behavior_differs: { label: 'Behavior differs', icon: Diff, tone: 'danger' },
  inconclusive: { label: "Couldn't compare", icon: CircleHelp, tone: 'warning' },
  needs_probe: { label: 'Needs a probe', icon: FlaskConical, tone: 'neutral' },
  same: { label: 'Same on tested inputs', icon: Equal, tone: 'success' },
  not_run: { label: 'Not run', icon: CircleDashed, tone: 'neutral' },
  unknown_edge: { label: 'Possible link', icon: Unlink, tone: 'neutral' },
}

/** Legend and "most important first" order. */
export const STATUS_PRIORITY: EvidenceStatus[] = ['behavior_differs', 'inconclusive', 'needs_probe', 'same', 'not_run', 'unknown_edge']

export function StatusBadge({ status, count, className }: { status: EvidenceStatus; count?: number; className?: string }) {
  const { label, icon: Icon, tone } = STATUS_META[status]
  return (
    <Badge variant="outline" className={cn(TONE_CLASSES[tone], className)}>
      <Icon aria-hidden="true" />
      {count === undefined ? label : `${count} · ${label}`}
    </Badge>
  )
}
