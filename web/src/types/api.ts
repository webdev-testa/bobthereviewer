/**
 * Types for the Lane 2 local server API
 * Source of truth: contracts/local-server-api.md
 */

export interface RunSummary {
  run_id: string
  generated_at: string
  base_ref: string
  head_ref: string
  triage_category: string
}

export interface StartRunRequest {
  before_ref: string
  after_ref: string
  probes: string[]
  prior_run_id?: string
}

export interface StartRunResponse {
  run_id: string
}

export interface DecideRequest {
  run_id: string
  symbol: string
  case_id: string
  probe_file: string
  verdict: 'intended' | 'unintended' | 'unresolved'
  rationale: string
}

export interface DecideResponse {
  file_path: string
  git_command: string
}

export interface ProgressEvent {
  run_id: string
  step:
    | 'triage'
    | 'analyze'
    | 'test_base'
    | 'test_head'
    | 'probe_base'
    | 'probe_head'
    | 'done'
    | 'error'
  status: 'started' | 'completed' | 'failed'
  message: string
  timestamp: string
}
