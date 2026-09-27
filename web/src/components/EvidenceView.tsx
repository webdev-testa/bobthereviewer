import { useCallback, useState, type ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SummaryCard } from '@/components/SummaryCard'
import { NeedsAttention } from '@/components/NeedsAttention'
import { ReviewDetails } from '@/components/ReviewDetails'
import { DecisionBadge } from '@/components/DecisionBadge'
import { EvidenceMap } from '@/components/EvidenceMap'
import { RepoMapTab } from '@/components/RepoMapTab'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { RepoMap } from '@/lib/repo-map'
import type { Evidence } from '@/types/evidence'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

interface Props {
  evidence: Evidence
  /** The run's repo map; null when it has none. */
  repoMap: RepoMap | null
}

export function EvidenceView({ evidence, repoMap }: Props) {
  const [tab, setTab] = useState('review')
  const showEvidence = useCallback(() => {
    setTab('review')
    requestAnimationFrame(() => document.getElementById('evidence-map-heading')?.scrollIntoView({ block: 'start' }))
  }, [])
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
      <Tabs value={tab} onValueChange={setTab} className="gap-6">
        <TabsList aria-label="Views">
          <TabsTrigger value="review">Review</TabsTrigger>
          <TabsTrigger value="repo">Repo map</TabsTrigger>
        </TabsList>
        <TabsContent value="review" className="space-y-8">
          <NeedsAttention evidence={evidence} />
          <EvidenceMap evidence={evidence} />
          <ReviewDetails evidence={evidence} />

          {evidence.prior_decisions?.length ? (
            <Section title="Earlier approved decisions">
              {evidence.prior_decisions.map((d) => <DecisionBadge key={`${d.run_id}:${d.symbol}:${d.case_id}`} decision={d} isHistory />)}
            </Section>
          ) : null}
        </TabsContent>
        <TabsContent value="repo">
          <RepoMapTab evidence={evidence} map={repoMap} onShowEvidence={showEvidence} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
