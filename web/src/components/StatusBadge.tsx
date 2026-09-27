import type { LucideIcon } from 'lucide-react'
import { CircleDashed, CircleHelp, Diff, Equal, FileSearch, FlaskConical, PencilLine } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TONE_CLASSES, type Tone } from '@/lib/tones'
import { cn } from '@/lib/utils'

export type EvidenceStatus =
  | 'behavior_differs' | 'inconclusive' | 'needs_probe' | 'same' | 'changed' | 'outside_diff' | 'unknown_edge'

export const STATUS_META: Record<EvidenceStatus, { label: string; icon: LucideIcon; tone: Tone }> = {
  behavior_differs: { label: 'Behavior differs', icon: Diff, tone: 'danger' },
  inconclusive: { label: 'Inconclusive', icon: CircleHelp, tone: 'warning' },
  needs_probe: { label: 'Needs a probe', icon: FlaskConical, tone: 'neutral' },
  same: { label: 'Same on tested cases', icon: Equal, tone: 'success' },
  changed: { label: 'Changed', icon: PencilLine, tone: 'info' },
  outside_diff: { label: 'Outside diff', icon: FileSearch, tone: 'neutral' },
  unknown_edge: { label: 'Unknown edge', icon: CircleDashed, tone: 'warning' },
}

/** Legend and "most important first" order. */
export const STATUS_PRIORITY: EvidenceStatus[] = [
  'behavior_differs', 'inconclusive', 'unknown_edge', 'needs_probe', 'same', 'outside_diff', 'changed',
]

export function StatusBadge({ status, count, className }: { status: EvidenceStatus; count?: number; className?: string }) {
  const { label, icon: Icon, tone } = STATUS_META[status]
  return (
    <Badge variant="outline" className={cn(TONE_CLASSES[tone], className)}>
      <Icon aria-hidden="true" />
      {count === undefined ? label : `${count} · ${label}`}
    </Badge>
  )
}
