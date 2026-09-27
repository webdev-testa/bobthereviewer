import { Info, CheckCircle2, AlertTriangle, HelpCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { DecisionRecord } from '@/types/evidence'

const VERDICT_CONFIG = {
  intended:   { label: 'Intended',   icon: <CheckCircle2 size={13} />, cls: 'text-success bg-success-muted border-success/30' },
  unintended: { label: 'Unintended', icon: <AlertTriangle size={13} />, cls: 'text-danger bg-danger-muted border-danger/30' },
  unresolved: { label: 'Unresolved', icon: <HelpCircle size={13} />,   cls: 'text-warning bg-warning-muted border-warning/30' },
}

interface Props { decision: DecisionRecord; isHistory?: boolean }

export function DecisionBadge({ decision, isHistory = false }: Props) {
  const cfg = VERDICT_CONFIG[decision.verdict]
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 space-y-1 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline" className={cn('flex items-center gap-1 text-xs', cfg.cls)}>
          {cfg.icon}{cfg.label}
        </Badge>
        <span className="text-xs text-muted font-mono">{decision.symbol}</span>
      </div>
      {decision.rationale && (
        <p className="text-xs text-muted">{decision.rationale}</p>
      )}
      {isHistory && (
        <div className="flex items-center gap-1 text-xs text-info mt-1">
          <Info size={12} />
          This is prior context, not approval of the current change.
        </div>
      )}
    </div>
  )
}
