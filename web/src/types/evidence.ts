/**
 * TypeScript types mirroring contracts/evidence.schema.json
 * Source of truth: contracts/evidence.schema.json (Lane 1)
 *
 * Key differences from spec draft:
 * - probe cases have separate execution_status + comparison_status (not a single status)
 * - callers have an optional via[] for two-hop paths
 * - top-level fixture: boolean marks illustrative data
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

export interface ViaEdge {
  symbol: string
  file_path: string
  line: number
}

export interface CallerInfo {
  symbol: string
  file_path: string
  line: number
  in_diff: boolean
  resolution: 'resolved'
  needs_probe: boolean
  via: ViaEdge[] | null
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

export type ExecutionStatus = 'success' | 'exception' | 'inconclusive'
export type ComparisonStatus = 'match' | 'differ' | 'inconclusive' | null

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
  execution_status: ExecutionStatus
  comparison_status: ComparisonStatus
  inconclusive_reason: string | null
  inconclusive_detail: string | null
  base_executed_at: string | null
  head_executed_at: string | null
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
  case_id?: string
  base_commit: string
  head_commit: string
  probe_file: string
  probe_hash: string
  observed_before: OutputValue
  observed_after: OutputValue
  verdict: 'intended' | 'unintended' | 'unresolved'
  rationale: string
  status: 'proposed' | 'approved'
  timestamp: string
}

export interface LanguageSupport {
  language: string
  adapter?: string
  /** full: Python (callers, tests, probes); static: callers only; static_same_file: same-file callers, beta. */
  tier: 'full' | 'static' | 'static_same_file'
}

export interface AnalysisLimits {
  max_hops: number
  notes: string[]
  languages?: LanguageSupport[]
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
  /** When true this is illustrative fixture data — show a clear label in the UI */
  fixture?: boolean
  triage: TriageInfo
  analysis_limits: AnalysisLimits
  changed_functions: ChangedFunction[]
  test_results: TestResults
  probe_results: ProbeResult[]
  /** Decision files in the reviewed branch that match a case of this run (proposed until merged). */
  decisions: DecisionRecord[]
  /** Approved decisions already on the default branch: prior context, not approval of this change. */
  prior_decisions?: DecisionRecord[]
}
