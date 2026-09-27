import { GitBranch } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { CallerInfo } from '@/types/evidence'

interface Props { caller: CallerInfo }

export function CallerRow({ caller }: Props) {
  const outsideDiff = !caller.in_diff
  return (
    <div className={cn(
      'flex items-start gap-2 rounded-md px-3 py-2 text-sm border',
      outsideDiff ? 'border-warning/40 bg-warning-muted' : 'border-border bg-surface-raised',
    )}>
      <GitBranch size={14} className="mt-0.5 shrink-0 text-muted" />
      <div className="flex-1 min-w-0">
        <span className="font-mono text-xs break-all">{caller.symbol}</span>
        <div className="text-xs text-muted mt-0.5">
          {caller.file_path}:{caller.line}
        </div>
      </div>
      <div className="flex gap-1 flex-wrap justify-end">
        {outsideDiff && (
          <Badge variant="outline" className="text-xs bg-warning-muted text-warning border-warning/30">
            Outside diff
          </Badge>
        )}
        {caller.needs_probe && (
          <Badge variant="outline" className="text-xs bg-neutral-muted text-neutral border-neutral/30">
            Needs a probe
          </Badge>
        )}
      </div>
    </div>
  )
}
