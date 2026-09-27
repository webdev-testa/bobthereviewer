import type { ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SummaryCard } from '@/components/SummaryCard'
import { NeedsAttention } from '@/components/NeedsAttention'
import { ReviewDetails } from '@/components/ReviewDetails'
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
      <NeedsAttention evidence={evidence} onSaveDecision={onSaveDecision} />
      <EvidenceMap evidence={evidence} />
      <ReviewDetails evidence={evidence} onSaveDecision={onSaveDecision} />

      {evidence.decisions.length > 0 && (
        <Section title="Prior decisions">
          {evidence.decisions.map((d, i) => <DecisionBadge key={i} decision={d} isHistory />)}
        </Section>
      )}
    </div>
  )
}
