import type { LucideIcon } from 'lucide-react'
import { CircleCheck, CircleHelp, Info, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TONE_CLASSES, type Tone } from '@/lib/tones'
import type { DecisionRecord } from '@/types/evidence'

const VERDICT_CONFIG: Record<DecisionRecord['verdict'], { label: string; icon: LucideIcon; tone: Tone }> = {
  intended:   { label: 'Intended',   icon: CircleCheck,   tone: 'success' },
  unintended: { label: 'Unintended', icon: TriangleAlert, tone: 'danger' },
  unresolved: { label: 'Unresolved', icon: CircleHelp,    tone: 'warning' },
}

interface Props { decision: DecisionRecord; isHistory?: boolean }

export function DecisionBadge({ decision, isHistory = false }: Props) {
  const { label, icon: Icon, tone } = VERDICT_CONFIG[decision.verdict]
  return (
    <div className="space-y-1 rounded-md border bg-muted/40 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={TONE_CLASSES[tone]}>
          <Icon aria-hidden="true" />{label}
        </Badge>
        <code className="text-xs text-muted-foreground">{decision.symbol}</code>
      </div>
      {decision.rationale && <p className="text-muted-foreground">{decision.rationale}</p>}
      {isHistory && (
        <p className="flex items-center gap-1 text-xs text-info">
          <Info aria-hidden="true" className="size-3" />
          This is prior context, not approval of the current change.
        </p>
      )}
    </div>
  )
}
