import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { StatusBadge, STATUS_PRIORITY, type EvidenceStatus } from '@/components/StatusBadge'
import { caseStatus, ProbeResultTable } from '@/components/ProbeResultTable'
import type { ProbeResult } from '@/types/evidence'

function counts(result: ProbeResult) {
  const tally = new Map<EvidenceStatus, number>()
  result.cases.forEach((c) => tally.set(caseStatus(c), (tally.get(caseStatus(c)) ?? 0) + 1))
  return STATUS_PRIORITY.filter((status) => tally.has(status)).map((status) => [status, tally.get(status)!] as const)
}

const needsAttention = (result: ProbeResult) => result.cases.some((c) => caseStatus(c) !== 'same')

interface Props {
  results: ProbeResult[]
  onSaveDecision?: (target: string, caseId: string, probeFile: string) => void
}

/** One row per probe; rows with a difference or an inconclusive case start open. */
export function ProbeResults({ results, onSaveDecision }: Props) {
  return (
    <Accordion type="multiple" defaultValue={results.filter(needsAttention).map((r) => r.probe_file)}>
      {results.map((result) => (
        <AccordionItem key={result.probe_file} value={result.probe_file}>
          <AccordionTrigger className="items-center hover:no-underline">
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
              <code className="font-semibold break-all">{result.target}</code>
              <span className="text-xs text-muted-foreground">{result.probe_file}</span>
              <span className="flex flex-wrap gap-1">
                {counts(result).map(([status, count]) => <StatusBadge key={status} status={status} count={count} />)}
              </span>
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <ProbeResultTable
              result={result}
              onSaveDecision={onSaveDecision ? (caseId) => onSaveDecision(result.target, caseId, result.probe_file) : undefined}
            />
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  )
}
