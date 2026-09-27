import type { ReactNode } from 'react'
import { ExternalLink, TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { TriageBadge } from '@/components/TriageBadge'
import { ChangedFunctionCard } from '@/components/ChangedFunctionCard'
import { TestResultTable } from '@/components/TestResultTable'
import { DecisionBadge } from '@/components/DecisionBadge'
import { EvidenceMap } from '@/components/EvidenceMap'
import type { Evidence } from '@/types/evidence'

interface Props {
  evidence: Evidence
  onSaveDecision?: (symbol: string, caseId: string, probeFile: string) => void
}

function formatTime(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

function Summary({ evidence }: { evidence: Evidence }) {
  return (
    <Card>
      <CardHeader className="gap-3">
        <p className="text-sm text-muted-foreground">Behavior review</p>
        <h1 className="text-2xl font-semibold tracking-tight break-words">{evidence.repository}</h1>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
          <span>base <code className="text-foreground">{evidence.base_ref}</code> ({evidence.base_commit.slice(0, 7)})</span>
          <span aria-hidden="true">→</span>
          <span>head <code className="text-foreground">{evidence.head_ref}</code> ({evidence.head_commit.slice(0, 7)})</span>
          <span aria-hidden="true">·</span>
          <time dateTime={evidence.generated_at}>{formatTime(evidence.generated_at)}</time>
        </p>
      </CardHeader>
      <Separator />
      <CardContent className="flex flex-col gap-4 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">Triage</span>
          <TriageBadge triage={evidence.triage} />
        </div>
        {evidence.ci_run_url?.startsWith('https://') ? (
          <Button asChild variant="outline" size="sm">
            <a href={evidence.ci_run_url} target="_blank" rel="noreferrer">
              GitHub Actions run
              <ExternalLink aria-hidden="true" />
            </a>
          </Button>
        ) : (
          <span className="text-sm text-muted-foreground">Run {evidence.run_id.slice(0, 8)}</span>
        )}
      </CardContent>
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
      <Summary evidence={evidence} />
      <EvidenceMap evidence={evidence} />

      <Section title="Changed functions">
        {evidence.changed_functions.length === 0
          ? <p className="text-sm text-muted-foreground">No changed functions detected.</p>
          : evidence.changed_functions.map((fn) => (
            <ChangedFunctionCard
              key={fn.symbol}
              fn={fn}
              probeResults={evidence.probe_results}
              onSaveDecision={onSaveDecision
                ? (caseId, probeFile) => onSaveDecision(fn.symbol, caseId, probeFile)
                : undefined}
            />
          ))}
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
