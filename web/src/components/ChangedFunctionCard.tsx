import { Code2, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CallerRow } from '@/components/CallerRow'
import { UnknownRefRow } from '@/components/UnknownRefRow'
import { ProbeResultTable } from '@/components/ProbeResultTable'
import { cn } from '@/lib/utils'
import type { ChangedFunction, ProbeResult } from '@/types/evidence'

interface Props {
  fn: ChangedFunction
  probeResults: ProbeResult[]
  onSaveDecision?: (caseId: string, probeFile: string) => void
}

export function ChangedFunctionCard({ fn, probeResults, onSaveDecision }: Props) {
  const [open, setOpen] = useState(true)
  const relatedProbes = probeResults.filter((p) => p.target === fn.symbol)

  return (
    <Card className="border-border">
      <CardHeader
        className="cursor-pointer select-none py-3 px-4"
        onClick={() => setOpen((o) => !o)}
      >
        <CardTitle className="flex items-center gap-2 text-sm font-mono font-medium">
          <Code2 size={15} className="text-info shrink-0" />
          <span className="break-all">{fn.symbol}</span>
          <span className="text-xs text-muted-foreground font-normal ml-1">{fn.file_path}</span>
          <ChevronDown size={14} className={cn('ml-auto shrink-0 transition-transform', !open && '-rotate-90')} />
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="px-4 pb-4 space-y-3">
          {fn.callers.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Callers</div>
              {fn.callers.map((c, i) => <CallerRow key={i} caller={c} />)}
            </div>
          )}
          {fn.unknown_references.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Unknown edges</div>
              {fn.unknown_references.map((r, i) => <UnknownRefRow key={i} ref_={r} />)}
            </div>
          )}
          {relatedProbes.map((p, i) => (
            <ProbeResultTable
              key={i}
              result={p}
              onSaveDecision={onSaveDecision ? (caseId) => onSaveDecision(caseId, p.probe_file) : undefined}
            />
          ))}
        </CardContent>
      )}
    </Card>
  )
}
