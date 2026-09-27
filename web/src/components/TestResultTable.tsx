import { CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { TestResults } from '@/types/evidence'

const STATUS_CONFIG = {
  pass:  { label: 'Pass',  icon: <CheckCircle2 size={13} />, cls: 'text-success bg-success-muted border-success/30' },
  fail:  { label: 'Fail',  icon: <XCircle size={13} />,      cls: 'text-danger bg-danger-muted border-danger/30' },
  error: { label: 'Error', icon: <AlertCircle size={13} />,  cls: 'text-warning bg-warning-muted border-warning/30' },
}

interface Props { testResults: TestResults }

export function TestResultTable({ testResults }: Props) {
  const nodeIds = Array.from(new Set([
    ...Object.keys(testResults.base),
    ...Object.keys(testResults.head),
  ])).sort()

  if (nodeIds.length === 0) return <div className="text-xs text-muted">No test results</div>

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Test</TableHead>
          <TableHead>Base</TableHead>
          <TableHead>Head</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {nodeIds.map((id) => {
          const base = testResults.base[id]
          const head = testResults.head[id]
          const baseCfg = base ? STATUS_CONFIG[base.status] : null
          const headCfg = head ? STATUS_CONFIG[head.status] : null
          const changed = base?.status !== head?.status
          return (
            <TableRow key={id} className={cn(changed && 'bg-warning-muted/40')}>
              <TableCell className="font-mono text-xs break-all">{id}</TableCell>
              <TableCell>
                {baseCfg && (
                  <Badge variant="outline" className={cn('flex items-center gap-1 text-xs w-fit', baseCfg.cls)}>
                    {baseCfg.icon}{baseCfg.label}
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                {headCfg && (
                  <Badge variant="outline" className={cn('flex items-center gap-1 text-xs w-fit', headCfg.cls)}>
                    {headCfg.icon}{headCfg.label}
                  </Badge>
                )}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
