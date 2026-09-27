import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/StatusBadge'
import { caseStatus } from '@/components/ProbeResultTable'
import type { Evidence } from '@/types/evidence'

interface Props {
  evidence: Evidence
  onSaveDecision?: (target: string, caseId: string, probeFile: string) => void
}

/** Only the cases a person has to look at: differences to decide on, and cases that couldn't be compared. */
export function NeedsAttention({ evidence, onSaveDecision }: Props) {
  const items = evidence.probe_results.flatMap((result) =>
    result.cases.filter((c) => caseStatus(c) !== 'same').map((c) => ({ result, c })),
  )
  if (!items.length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle><h2 className="text-lg font-semibold">Needs your attention</h2></CardTitle>
        <CardDescription>
          For each difference, decide whether it was intended. Cases that couldn't be compared say why.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-md border">
          {items.map(({ result, c }) => (
            <li key={`${result.probe_file}:${c.id}`} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1 space-y-1">
                <p className="flex flex-wrap items-center gap-x-2 text-sm">
                  <code className="font-semibold break-all">{result.target}</code>
                  <span className="text-muted-foreground">case <code>{c.id}</code></span>
                </p>
                <p className="flex flex-wrap items-center gap-2 font-mono text-sm">
                  <span>{JSON.stringify(c.base_output)}</span>
                  <ArrowRight aria-label="became" className="size-3.5 text-muted-foreground" />
                  <span>{JSON.stringify(c.head_output)}</span>
                </p>
                {c.inconclusive_reason ? (
                  <p className="text-xs text-muted-foreground">
                    {c.inconclusive_reason}{c.inconclusive_detail ? `: ${c.inconclusive_detail}` : ''}
                  </p>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={caseStatus(c)} />
                {onSaveDecision && c.comparison_status === 'differ' ? (
                  <Button size="sm" onClick={() => onSaveDecision(result.target, c.id, result.probe_file)}>Save decision</Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
