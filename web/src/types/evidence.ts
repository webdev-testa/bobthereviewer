/**
 * TypeScript types mirroring contracts/evidence.schema.json
 * Source of truth: contracts/evidence.schema.json (Lane 1)
 */

export type TriageCategory =
  | 'docs-only'
  | 'tests-only'
  | 'config-deps'
  | 'no-semantic-change'
  | 'code'

export interface TriageInfo {
  category: TriageCategory
  skipped: boolean
  skip_reason: string | null
}

export interface CallerInfo {
  symbol: string
  file_path: string
  line: number
  in_diff: boolean
  resolution: 'resolved' | 'unknown'
  needs_probe: boolean
}

export interface UnknownRef {
  file_path: string
  line: number
  reason: string
}

export interface ChangedFunction {
  symbol: string
  file_path: string
  callers: CallerInfo[]
  unknown_references: UnknownRef[]
}

export type TestStatus = 'pass' | 'fail' | 'error'

export interface TestResult {
  status: TestStatus
  message: string | null
}

export interface TestResults {
  base: Record<string, TestResult>
  head: Record<string, TestResult>
}

export type CaseStatus = 'match' | 'differ' | 'inconclusive'

export type OutputValue =
  | string
  | number
  | boolean
  | null
  | unknown[]
  | Record<string, unknown>
  | { exception: string; message: string }

export interface ProbeCase {
  id: string
  args: unknown[]
  kwargs: Record<string, unknown>
  base_output: OutputValue
  head_output: OutputValue
  status: CaseStatus
  inconclusive_reason: string | null
  base_executed_at: string
  head_executed_at: string
}

export interface ProbeResult {
  probe_file: string
  probe_hash: string
  target: string
  prior_difference_run_id: string | null
  cases: ProbeCase[]
}

export interface DecisionRecord {
  schema_version: string
  run_id: string
  repository: string
  file_path: string
  symbol: string
  base_commit: string
  head_commit: string
  probe_file: string
  probe_hash: string
  observed_before: OutputValue
  observed_after: OutputValue
  verdict: 'intended' | 'unintended' | 'unresolved'
  rationale: string
  status: 'proposed'
  timestamp: string
}

export interface AnalysisLimits {
  max_hops: number
  notes: string[]
}

export interface Evidence {
  schema_version: string
  run_id: string
  generated_at: string
  repository: string
  base_ref: string
  head_ref: string
  base_commit: string
  head_commit: string
  prior_run_id: string | null
  ci_run_url: string | null
  frozen_suite_hash: string | null
  triage: TriageInfo
  analysis_limits: AnalysisLimits
  changed_functions: ChangedFunction[]
  test_results: TestResults
  probe_results: ProbeResult[]
  decisions: DecisionRecord[]
}
