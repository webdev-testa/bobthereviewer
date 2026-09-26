/**
 * Rich fixture exercising all statuses and edge cases.
 * Used for development and the judge page before real evidence is available.
 */
import type { Evidence } from '@/types/evidence'

export const evidenceFixture: Evidence = {
  schema_version: '1',
  run_id: 'a1b2c3d4-0000-0000-0000-000000000001',
  generated_at: '2025-01-15T10:30:00Z',
  repository: 'https://github.com/webdev-testa/pocbobbin',
  base_ref: 'demo-base',
  head_ref: 'demo-rounding-change',
  base_commit: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  head_commit: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  prior_run_id: null,
  ci_run_url: 'https://github.com/webdev-testa/pocbobbin/actions/runs/12345',
  frozen_suite_hash: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
  triage: {
    category: 'code',
    skipped: false,
    skip_reason: null,
  },
  analysis_limits: {
    max_hops: 2,
    notes: [],
  },
  changed_functions: [
    {
      symbol: 'discount.apply_discount',
      file_path: 'discount.py',
      callers: [
        {
          symbol: 'invoice.calculate_invoice',
          file_path: 'invoice.py',
          line: 42,
          in_diff: false,
          resolution: 'resolved',
          needs_probe: true,
        },
        {
          symbol: 'discount.apply_discount_batch',
          file_path: 'discount.py',
          line: 88,
          in_diff: true,
          resolution: 'resolved',
          needs_probe: false,
        },
      ],
      unknown_references: [
        {
          file_path: 'discount.py',
          line: 101,
          reason: 'dynamic call expression (getattr/subscript/lambda)',
        },
      ],
    },
  ],
  test_results: {
    base: {
      'tests/test_discount.py::test_apply_discount': { status: 'pass', message: null },
      'tests/test_invoice.py::test_calculate_invoice': { status: 'pass', message: null },
      'tests/test_discount.py::test_edge_case': { status: 'fail', message: 'AssertionError: expected 0.9 got 0.89' },
    },
    head: {
      'tests/test_discount.py::test_apply_discount': { status: 'pass', message: null },
      'tests/test_invoice.py::test_calculate_invoice': { status: 'pass', message: null },
      'tests/test_discount.py::test_edge_case': { status: 'fail', message: 'AssertionError: expected 0.9 got 0.89' },
    },
  },
  probe_results: [
    {
      probe_file: '.bobreviewer/probes/invoice_basic.json',
      probe_hash: 'cafebabecafebabecafebabecafebabecafebabecafebabecafebabecafebabe',
      target: 'invoice.calculate_invoice',
      prior_difference_run_id: null,
      cases: [
        {
          id: 'basic-100',
          args: [100, 0.1],
          kwargs: {},
          base_output: 100.0,
          head_output: 99.99,
          status: 'differ',
          inconclusive_reason: null,
          base_executed_at: '2025-01-15T10:28:00Z',
          head_executed_at: '2025-01-15T10:29:00Z',
        },
        {
          id: 'zero-discount',
          args: [50, 0],
          kwargs: {},
          base_output: 50.0,
          head_output: 50.0,
          status: 'match',
          inconclusive_reason: null,
          base_executed_at: '2025-01-15T10:28:01Z',
          head_executed_at: '2025-01-15T10:29:01Z',
        },
        {
          id: 'nondeterministic-case',
          args: [75, 0.05],
          kwargs: {},
          base_output: null,
          head_output: null,
          status: 'inconclusive',
          inconclusive_reason: 'nondeterminism_detected',
          base_executed_at: '2025-01-15T10:28:02Z',
          head_executed_at: '2025-01-15T10:29:02Z',
        },
      ],
    },
  ],
  decisions: [
    {
      schema_version: '1',
      run_id: 'a1b2c3d4-0000-0000-0000-000000000000',
      repository: 'https://github.com/webdev-testa/pocbobbin',
      file_path: 'discount.py',
      symbol: 'discount.apply_discount',
      base_commit: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      head_commit: 'cccccccccccccccccccccccccccccccccccccccc',
      probe_file: '.bobreviewer/probes/invoice_basic.json',
      probe_hash: 'cafebabecafebabecafebabecafebabecafebabecafebabecafebabecafebabe',
      observed_before: 100.0,
      observed_after: 100.0,
      verdict: 'intended',
      rationale: 'Tax rate updated per Q1 policy memo. Approved by finance team.',
      status: 'proposed',
      timestamp: '2025-01-10T09:00:00Z',
    },
  ],
}
