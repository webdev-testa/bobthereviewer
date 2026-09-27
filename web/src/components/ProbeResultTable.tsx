import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { StatusBadge, type EvidenceStatus } from '@/components/StatusBadge'
import type { ProbeCase, ProbeResult } from '@/types/evidence'

/** A case's outcome in the map's vocabulary; anything not compared counts as inconclusive. */
export function caseStatus(c: ProbeCase): EvidenceStatus {
  if (c.comparison_status === 'differ') return 'behavior_differs'
  if (c.comparison_status === 'match') return 'same'
  return 'inconclusive'
}

interface Props {
  result: ProbeResult
  onSaveDecision?: (caseId: string) => void
}

export function ProbeResultTable({ result, onSaveDecision }: Props) {
  return (
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
        {result.cases.map((c) => (
          <TableRow key={c.id}>
            <TableCell className="font-mono text-xs">{c.id}</TableCell>
            <TableCell className="font-mono text-xs">{JSON.stringify(c.base_output)}</TableCell>
            <TableCell className="font-mono text-xs">{JSON.stringify(c.head_output)}</TableCell>
            <TableCell>
              <StatusBadge status={caseStatus(c)} />
              {c.inconclusive_reason && (
                <div className="mt-0.5 text-xs text-muted-foreground">{c.inconclusive_reason}</div>
              )}
              {c.inconclusive_detail && (
                <div className="mt-0.5 max-w-[200px] truncate font-mono text-xs text-muted-foreground">{c.inconclusive_detail}</div>
              )}
            </TableCell>
            {onSaveDecision && (
              <TableCell>
                {c.comparison_status === 'differ' && (
                  <Button variant="outline" size="xs" onClick={() => onSaveDecision(c.id)}>Save decision</Button>
                )}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
