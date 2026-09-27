import type { ReactNode } from 'react'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ProbeResults } from '@/components/ProbeResults'
import { TestResultTable } from '@/components/TestResultTable'
import type { Evidence, TestResults } from '@/types/evidence'

function testSummary(results: TestResults) {
  const ids = new Set([...Object.keys(results.base), ...Object.keys(results.head)])
  const changed = [...ids].filter((id) => results.base[id]?.status !== results.head[id]?.status).length
  const failing = [...ids].filter((id) => results.head[id] && results.head[id].status !== 'pass').length
  if (!ids.size) return { text: 'No tests ran', attention: false }
  if (changed) return { text: `${changed} of ${ids.size} tests changed result between base and head`, attention: true }
  if (failing) return { text: `${ids.size} tests · ${failing} failing on both sides (not caused by this change)`, attention: false }
  return { text: `${ids.size} tests · all pass on both sides`, attention: false }
}

function Row({ value, title, summary, children }: { value: string; title: string; summary: string; children: ReactNode }) {
  return (
    <AccordionItem value={value}>
      <AccordionTrigger className="hover:no-underline">
        <span className="flex flex-wrap items-baseline gap-x-3">
          <span className="font-medium">{title}</span>
          <span className="text-sm font-normal text-muted-foreground">{summary}</span>
        </span>
      </AccordionTrigger>
      <AccordionContent>{children}</AccordionContent>
    </AccordionItem>
  )
}

interface Props {
  evidence: Evidence
  onSaveDecision?: (target: string, caseId: string, probeFile: string) => void
}

/** Everything behind the verdict, one collapsible row each; only a test regression opens by default. */
export function ReviewDetails({ evidence, onSaveDecision }: Props) {
  const probes = evidence.probe_results
  const caseCount = probes.reduce((n, p) => n + p.cases.length, 0)
  const tests = testSummary(evidence.test_results)
  const notes = evidence.analysis_limits.notes
  return (
    <Card>
      <CardHeader><CardTitle><h2 className="text-lg font-semibold">Details</h2></CardTitle></CardHeader>
      <CardContent>
        <Accordion type="multiple" defaultValue={tests.attention ? ['tests'] : []}>
          <Row value="probes" title="Probe results" summary={probes.length ? `${probes.length} probe${probes.length === 1 ? '' : 's'} · ${caseCount} cases` : 'No probes ran'}>
            {probes.length
              ? <ProbeResults results={probes} onSaveDecision={onSaveDecision} />
              : <p className="text-sm text-muted-foreground">Nothing was executed on both revisions. The map shows which callers need a probe.</p>}
          </Row>
          <Row value="tests" title="Tests" summary={evidence.triage.skipped ? 'Skipped' : tests.text}>
            {evidence.triage.skipped
              ? <p className="text-sm text-muted-foreground">Execution skipped: {evidence.triage.skip_reason ?? 'docs-only change'}.</p>
              : <TestResultTable testResults={evidence.test_results} />}
          </Row>
          <Row value="limits" title="What this review can't tell you" summary={`${notes.length} note${notes.length === 1 ? '' : 's'} · callers traced ${evidence.analysis_limits.max_hops} hops`}>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              <li>Callers are traced up to {evidence.analysis_limits.max_hops} calls away; anything further is not shown.</li>
              <li>Probes prove only the inputs they tried; matching cases do not certify the function is correct.</li>
              {notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </Row>
        </Accordion>
      </CardContent>
    </Card>
  )
}
