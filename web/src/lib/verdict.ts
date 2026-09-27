import type { EvidenceStatus } from '@/components/StatusBadge'
import { decisionFor } from '@/lib/decision-context'
import { isTestSymbol } from '@/lib/evidence-map'
import type { Tone } from '@/lib/tones'
import type { Evidence } from '@/types/evidence'

export interface Verdict {
  tone: Tone
  headline: string
  counts: [EvidenceStatus, number][]
}

/** The one-line answer to "is this change safe?", plus the counts behind it. */
export function reviewVerdict(evidence: Evidence): Verdict {
  const cases = evidence.probe_results.flatMap((p) => p.cases)
  const differs = cases.filter((c) => c.comparison_status === 'differ').length
  const same = cases.filter((c) => c.comparison_status === 'match').length
  const inconclusive = cases.length - differs - same
  const probed = new Set(evidence.probe_results.map((p) => p.target))
  // Same rule as the map's "Needs a probe" boxes, so the two never disagree.
  const unprobed = new Set(
    evidence.changed_functions.flatMap((fn) => fn.callers)
      .filter((c) => c.needs_probe && !c.in_diff && !isTestSymbol(c.symbol) && !probed.has(c.symbol))
      .map((c) => c.symbol),
  ).size
  const unknown = evidence.changed_functions.reduce((n, fn) => n + fn.unknown_references.length, 0)

  const counts: [EvidenceStatus, number][] = [
    ['behavior_differs', differs], ['inconclusive', inconclusive], ['same', same],
    ['needs_probe', unprobed], ['unknown_edge', unknown],
  ]
  const nonZero = counts.filter(([, n]) => n > 0)
  const of = `of ${cases.length} tested case${cases.length === 1 ? '' : 's'}`

  if (evidence.triage.skipped) {
    return { tone: 'neutral', headline: `Execution skipped: ${evidence.triage.skip_reason ?? 'docs-only change'}.`, counts: nonZero }
  }
  if (differs) {
    const undecided = evidence.probe_results.flatMap((p) => p.cases
      .filter((c) => c.comparison_status === 'differ' && !decisionFor(evidence, p.target, c.id))).length
    const next = undecided === differs ? 'Your decision is needed.'
      : undecided ? `${undecided} still need a decision.`
      : 'Every difference has a decision (proposed until merged).'
    return { tone: 'danger', headline: `Behavior differs in ${differs} ${of}. ${next}`, counts: nonZero }
  }
  if (!cases.length) {
    return { tone: 'neutral', headline: 'No probes ran, so no behavior was compared.', counts: nonZero }
  }
  if (inconclusive) {
    return { tone: 'warning', headline: `${inconclusive} ${of} could not be compared.`, counts: nonZero }
  }
  return { tone: 'success', headline: `Same on all ${cases.length} tested cases.`, counts: nonZero }
}
