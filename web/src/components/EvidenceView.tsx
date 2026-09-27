import type { ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SummaryCard } from '@/components/SummaryCard'
import { ProbeResults } from '@/components/ProbeResults'
import { TestResultTable } from '@/components/TestResultTable'
import { DecisionBadge } from '@/components/DecisionBadge'
import { EvidenceMap } from '@/components/EvidenceMap'
import type { Evidence } from '@/types/evidence'

interface Props {
  evidence: Evidence
  onSaveDecision?: (symbol: string, caseId: string, probeFile: string) => void
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

export function EvidenceView({ evidence, onSaveDecision }: Props) {
  return (
    <div className="space-y-8">
      {evidence.fixture && (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <AlertTitle>FIXTURE — not real evidence</AlertTitle>
          <AlertDescription>
            Replace with output from <code>bobreviewer run</code>. Nothing on this page came from a real run.
          </AlertDescription>
        </Alert>
      )}
      <SummaryCard evidence={evidence} />
      <EvidenceMap evidence={evidence} />

      <Section title="Probe results">
        {evidence.probe_results.length === 0
          ? <p className="text-sm text-muted-foreground">No probes ran, so nothing was executed on both revisions. The map shows which callers need one.</p>
          : <ProbeResults results={evidence.probe_results} onSaveDecision={onSaveDecision} />}
      </Section>

      <Section title="Test results">
        {evidence.triage.skipped
          ? <p className="text-sm text-warning">Execution skipped — {evidence.triage.skip_reason ?? 'docs-only diff'}</p>
          : <TestResultTable testResults={evidence.test_results} />}
      </Section>

      {evidence.decisions.length > 0 && (
        <Section title="Prior decisions">
          {evidence.decisions.map((d, i) => <DecisionBadge key={i} decision={d} isHistory />)}
        </Section>
      )}
    </div>
  )
}
