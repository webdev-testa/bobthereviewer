import { CheckCircle2, AlertTriangle, HelpCircle } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ProbeResult } from '@/types/evidence'

const COMPARISON_CONFIG = {
  match:        { label: 'Same on tested cases', icon: <CheckCircle2 size={14} />, cls: 'text-success bg-success-muted border-success/30' },
  differ:       { label: 'Behavior differs',     icon: <AlertTriangle size={14} />, cls: 'text-danger bg-danger-muted border-danger/30' },
  inconclusive: { label: 'Inconclusive',         icon: <HelpCircle size={14} />,   cls: 'text-warning bg-warning-muted border-warning/30' },
}

interface Props {
  result: ProbeResult
  onSaveDecision?: (caseId: string) => void
}

export function ProbeResultTable({ result, onSaveDecision }: Props) {
  return (
    <div className="space-y-1">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <code className="font-semibold">{result.target}</code>
        <span className="text-xs text-muted-foreground">{result.probe_file}</span>
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
            <TableHead>Before</TableHead>
            <TableHead>After</TableHead>
            <TableHead>Result</TableHead>
            {onSaveDecision && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.cases.map((c) => {
            const execStatus = c.execution_status
            const cmpStatus = c.comparison_status
            const cfg = cmpStatus ? COMPARISON_CONFIG[cmpStatus] : null
            const isInconclusive = execStatus === 'inconclusive'
            const canDecide = cmpStatus === 'differ'

            return (
              <TableRow key={c.id}>
                <TableCell className="font-mono text-xs">{c.id}</TableCell>
                <TableCell className="font-mono text-xs">{JSON.stringify(c.base_output)}</TableCell>
                <TableCell className="font-mono text-xs">{JSON.stringify(c.head_output)}</TableCell>
                <TableCell>
                  {cfg && (
                    <Badge variant="outline" className={cn('flex items-center gap-1 text-xs w-fit', cfg.cls)}>
                      {cfg.icon}{cfg.label}
                    </Badge>
                  )}
                  {isInconclusive && !cfg && (
                    <Badge variant="outline" className="flex items-center gap-1 text-xs w-fit text-warning bg-warning-muted border-warning/30">
                      <HelpCircle size={14} />Inconclusive
                    </Badge>
                  )}
                  {c.inconclusive_reason && (
                    <div className="text-xs text-muted-foreground mt-0.5">{c.inconclusive_reason}</div>
                  )}
                  {c.inconclusive_detail && (
                    <div className="text-xs text-muted-foreground font-mono mt-0.5 truncate max-w-[200px]">{c.inconclusive_detail}</div>
                  )}
                </TableCell>
                {onSaveDecision && (
                  <TableCell>
                    {canDecide && (
                      <button
                        onClick={() => onSaveDecision(c.id)}
                        className="text-xs underline text-info hover:text-info/80 focus-visible:ring-2 focus-visible:ring-info rounded"
                      >
                        Save decision
                      </button>
                    )}
                  </TableCell>
                )}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
