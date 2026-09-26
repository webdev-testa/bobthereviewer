import { CheckCircle2, AlertTriangle, HelpCircle } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ProbeResult } from '@/types/evidence'

const STATUS_CONFIG = {
  match:        { label: 'Same on tested cases', icon: <CheckCircle2 size={14} />, cls: 'text-success bg-success-muted border-success/30' },
  differ:       { label: 'Behavior differs',     icon: <AlertTriangle size={14} />, cls: 'text-danger bg-danger-muted border-danger/30' },
  inconclusive: { label: 'Inconclusive',         icon: <HelpCircle size={14} />,   cls: 'text-warning bg-warning-muted border-warning/30' },
}

interface Props { result: ProbeResult; onSaveDecision?: (caseId: string) => void }

export function ProbeResultTable({ result, onSaveDecision }: Props) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted font-mono mb-1">{result.probe_file}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
            <TableHead>Before</TableHead>
            <TableHead>After</TableHead>
            <TableHead>Status</TableHead>
            {onSaveDecision && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.cases.map((c) => {
            const cfg = STATUS_CONFIG[c.status]
            return (
              <TableRow key={c.id}>
                <TableCell className="font-mono text-xs">{c.id}</TableCell>
                <TableCell className="font-mono text-xs">{JSON.stringify(c.base_output)}</TableCell>
                <TableCell className="font-mono text-xs">{JSON.stringify(c.head_output)}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={cn('flex items-center gap-1 text-xs w-fit', cfg.cls)}>
                    {cfg.icon}{cfg.label}
                  </Badge>
                  {c.inconclusive_reason && (
                    <div className="text-xs text-muted mt-0.5">{c.inconclusive_reason}</div>
                  )}
                </TableCell>
                {onSaveDecision && c.status === 'differ' && (
                  <TableCell>
                    <button
                      onClick={() => onSaveDecision(c.id)}
                      className="text-xs underline text-info hover:text-info/80 focus-visible:ring-2 focus-visible:ring-info rounded"
                    >
                      Save decision
                    </button>
                  </TableCell>
                )}
                {onSaveDecision && c.status !== 'differ' && <TableCell />}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
