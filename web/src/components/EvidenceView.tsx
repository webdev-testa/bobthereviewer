import { Separator } from '@/components/ui/separator'
import { TriageBadge } from '@/components/TriageBadge'
import { ChangedFunctionCard } from '@/components/ChangedFunctionCard'
import { TestResultTable } from '@/components/TestResultTable'
import { DecisionBadge } from '@/components/DecisionBadge'
import { CallerMap } from '@/components/CallerMap'
import type { Evidence } from '@/types/evidence'

interface Props {
  evidence: Evidence
  onSaveDecision?: (symbol: string, caseId: string) => void
}

export function EvidenceView({ evidence, onSaveDecision }: Props) {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <TriageBadge triage={evidence.triage} />
          <span className="text-xs text-muted font-mono">{evidence.base_ref} → {evidence.head_ref}</span>
        </div>
        <div className="text-xs text-muted">Run {evidence.run_id.slice(0, 8)} · {new Date(evidence.generated_at).toLocaleString()}</div>
        {evidence.ci_run_url && (
          <a href={evidence.ci_run_url} className="text-xs text-info underline" target="_blank" rel="noopener noreferrer">
            CI run ↗
          </a>
        )}
      </div>

      <Separator />

      {/* Changed functions */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Changed functions</h2>
        {evidence.changed_functions.length === 0
          ? <p className="text-xs text-muted">No changed functions detected.</p>
          : evidence.changed_functions.map((fn) => (
            <div key={fn.symbol} className="space-y-2">
              <ChangedFunctionCard
                fn={fn}
                probeResults={evidence.probe_results}
                onSaveDecision={onSaveDecision ? (caseId) => onSaveDecision(fn.symbol, caseId) : undefined}
              />
              <CallerMap fn={fn} />
            </div>
          ))
        }
      </section>

      <Separator />

      {/* Test results */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Test results</h2>
        {evidence.triage.skipped
          ? <p className="text-xs text-warning">Execution skipped — {evidence.triage.skip_reason ?? 'docs-only diff'}</p>
          : <TestResultTable testResults={evidence.test_results} />
        }
      </section>

      {/* Decisions */}
      {evidence.decisions.length > 0 && (
        <>
          <Separator />
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">Prior decisions</h2>
            {evidence.decisions.map((d, i) => (
              <DecisionBadge key={i} decision={d} isHistory />
            ))}
          </section>
        </>
      )}
    </div>
  )
}
