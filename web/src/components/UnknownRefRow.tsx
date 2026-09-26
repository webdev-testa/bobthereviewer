import { HelpCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { UnknownRef } from '@/types/evidence'

interface Props { ref_: UnknownRef }

export function UnknownRefRow({ ref_ }: Props) {
  return (
    <div className="flex items-start gap-2 rounded-md px-3 py-2 text-sm border border-neutral/30 bg-neutral-muted">
      <HelpCircle size={14} className="mt-0.5 shrink-0 text-neutral" />
      <div className="flex-1 min-w-0">
        <span className="font-mono text-xs break-all">{ref_.file_path}:{ref_.line}</span>
        <div className="text-xs text-muted mt-0.5">{ref_.reason}</div>
      </div>
      <Badge variant="outline" className="text-xs bg-neutral-muted text-neutral border-neutral/30 shrink-0">
        Unknown edge
      </Badge>
    </div>
  )
}
