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

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

export function EvidenceView({ evidence }: { evidence: Evidence }) {
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
      <NeedsAttention evidence={evidence} />
      <EvidenceMap evidence={evidence} />
      <ReviewDetails evidence={evidence} />

      {evidence.prior_decisions?.length ? (
        <Section title="Earlier approved decisions">
          {evidence.prior_decisions.map((d) => <DecisionBadge key={`${d.run_id}:${d.symbol}:${d.case_id}`} decision={d} isHistory />)}
        </Section>
      ) : null}
    </div>
  )
}
