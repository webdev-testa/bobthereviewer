import { createContext, useContext } from 'react'
import type { DecisionRecord, Evidence } from '@/types/evidence'

export const caseKey = (target: string, caseId: string) => `${target}::${caseId}`

export interface DecisionActions {
  /** Opens Save decision (local UI) or its "not saved" preview (judge page); absent = read-only. */
  save?: (target: string, caseId: string, probeFile: string) => void
  /** Cases saved in this session: written to disk but not in this run's evidence until committed. */
  saved: ReadonlySet<string>
}

// Every page that can save decisions provides this, so rows read it instead of threading props.
export const DecisionContext = createContext<DecisionActions>({ saved: new Set() })
export const useDecisionActions = () => useContext(DecisionContext)

/** The branch's own decision for one probe case, if the run found one. */
export function decisionFor(evidence: Evidence, target: string, caseId: string): DecisionRecord | undefined {
  return evidence.decisions.find((d) => d.symbol === target && d.case_id === caseId)
}
