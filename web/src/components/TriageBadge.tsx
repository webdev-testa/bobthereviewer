import { CheckCircle2, AlertTriangle, HelpCircle, FileQuestion, Layers } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { TriageInfo } from '@/types/evidence'

const CONFIG: Record<string, { label: string; icon: React.ReactNode; cls: string }> = {
  'code':               { label: 'Code change',           icon: <Layers size={13} />,         cls: 'bg-info-muted text-info border-info/30' },
  'tests-only':         { label: 'Tests only',            icon: <CheckCircle2 size={13} />,   cls: 'bg-neutral-muted text-neutral border-neutral/30' },
  'docs-only':          { label: 'Docs only',             icon: <FileQuestion size={13} />,   cls: 'bg-neutral-muted text-neutral border-neutral/30' },
  'config-deps':        { label: 'Config / deps',         icon: <AlertTriangle size={13} />,  cls: 'bg-warning-muted text-warning border-warning/30' },
  'no-semantic-change': { label: 'No semantic change',    icon: <CheckCircle2 size={13} />,   cls: 'bg-neutral-muted text-neutral border-neutral/30' },
}

interface Props { triage: TriageInfo }

export function TriageBadge({ triage }: Props) {
  const cfg = CONFIG[triage.category] ?? { label: triage.category, icon: <HelpCircle size={13} />, cls: 'bg-neutral-muted text-neutral' }
  return (
    <span className="flex items-center gap-2 flex-wrap">
      <Badge variant="outline" className={cn('flex items-center gap-1 text-xs', cfg.cls)}>
        {cfg.icon}{cfg.label}
      </Badge>
      {triage.skipped && (
        <Badge variant="outline" className="text-xs bg-warning-muted text-warning border-warning/30">
          <AlertTriangle size={13} className="mr-1" />Execution skipped — {triage.skip_reason ?? 'docs-only diff'}
        </Badge>
      )}
    </span>
  )
}
