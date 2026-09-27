/**
 * Rich fixture matching the real contracts/evidence.schema.json shape.
 * Kept in sync with tests/fixtures/evidence.fixture.json (Lane 1's canonical fixture).
 */
import type { Evidence } from '@/types/evidence'

export const evidenceFixture: Evidence = {
  schema_version: '1',
  fixture: true,
  run_id: '00000000-0000-0000-0000-000000000001',
  generated_at: '2025-01-15T10:30:00Z',
  repository: 'https://github.com/webdev-testa/pocbobbin',
  base_ref: 'demo-base',
  head_ref: 'demo-rounding-change',
  base_commit: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  head_commit: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  prior_run_id: null,
  ci_run_url: 'https://github.com/webdev-testa/pocbobbin/actions/runs/1',
  frozen_suite_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  triage: { category: 'code', skipped: false, skip_reason: null },
  analysis_limits: {
    max_hops: 2,
    notes: ['FIXTURE — not real evidence. Replace with output from bobreviewer run.'],
  },
  changed_functions: [
    {
      symbol: 'sample_project.pricing.discount.apply_discount',
      file_path: 'sample_project/pricing/discount.py',
      callers: [
        {
          symbol: 'sample_project.pricing.invoice.calculate_invoice',
          file_path: 'sample_project/pricing/invoice.py',
          line: 18,
          in_diff: false,
          resolution: 'resolved',
          needs_probe: true,
          via: null,
        },
        {
          symbol: 'sample_project.pricing.batch.apply_batch',
          file_path: 'sample_project/pricing/batch.py',
          line: 5,
          in_diff: false,
          resolution: 'resolved',
          needs_probe: false,
          via: [{ symbol: 'sample_project.pricing.invoice.calculate_invoice', file_path: 'sample_project/pricing/invoice.py', line: 18 }],
        },
      ],
      unknown_references: [
        {
          file_path: 'sample_project/pricing/utils.py',
          line: 42,
          reason: 'Dynamic reference via getattr — cannot resolve statically',
        },
      ],
    },
  ],
  test_results: {
    base: {
      'tests/test_discount.py::test_basic_discount': { status: 'pass', message: null },
      'tests/test_discount.py::test_zero_discount':  { status: 'pass', message: null },
      'tests/test_invoice.py::test_invoice_total':   { status: 'pass', message: null },
    },
    head: {
      'tests/test_discount.py::test_basic_discount': { status: 'pass', message: null },
      'tests/test_discount.py::test_zero_discount':  { status: 'pass', message: null },
      'tests/test_invoice.py::test_invoice_total':   { status: 'pass', message: null },
    },
  },
  probe_results: [
    {
      probe_file: '.bobreviewer/probes/invoice_basic.json',
      probe_hash: 'cafebabecafebabecafebabecafebabecafebabecafebabecafebabecafebabe',
      target: 'sample_project.pricing.invoice.calculate_invoice',
      prior_difference_run_id: null,
      cases: [
        {
          id: 'basic-100',
          args: [100, 0.1],
          kwargs: {},
          base_output: 100.0,
          head_output: 99.99,
          execution_status: 'success',
          comparison_status: 'differ',
          inconclusive_reason: null,
          inconclusive_detail: null,
          base_executed_at: '2025-01-15T10:28:00Z',
          head_executed_at: '2025-01-15T10:29:00Z',
        },
        {
          id: 'zero-discount',
          args: [50, 0],
          kwargs: {},
          base_output: 50.0,
          head_output: 50.0,
          execution_status: 'success',
          comparison_status: 'match',
          inconclusive_reason: null,
          inconclusive_detail: null,
          base_executed_at: '2025-01-15T10:28:01Z',
          head_executed_at: '2025-01-15T10:29:01Z',
        },
        {
          id: 'broken-import-case',
          args: [75, 0.05],
          kwargs: {},
          base_output: null,
          head_output: null,
          execution_status: 'inconclusive',
          comparison_status: null,
          inconclusive_reason: 'import_error',
          inconclusive_detail: "ModuleNotFoundError: No module named 'missing_dep'",
          base_executed_at: null,
          head_executed_at: null,
        },
      ],
    },
  ],
  decisions: [
    {
      schema_version: '1',
      run_id: '00000000-0000-0000-0000-000000000000',
      repository: 'https://github.com/webdev-testa/pocbobbin',
      file_path: 'sample_project/pricing/discount.py',
      symbol: 'sample_project.pricing.discount.apply_discount',
      case_id: 'basic-100',
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
