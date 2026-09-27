## bobthereviewer report

| | |
|---|---|
| **Run** | `f8d3b4b8` |
| **Base** | `a4c603d6febb2b5e57f412bff8f1c0a3f29a9f37` → `7358d1e5d33f7dbebb9c1bb5a003d6710dc18f25` |
| **Triage** | Code change |
| **Analyzed as** | Python (full) |

### Changed functions

#### `discount.apply_discount` — `discount.py`

**Callers**

| Symbol | File | Line | In diff? | Note |
|---|---|---|---|---|
| `invoice.calculate_invoice` | `invoice.py` | 8 | **No — outside diff** |  |

**4 test(s) call it:** `test_fifty_percent`, `test_no_discount`, `test_result_is_float`, `test_zero_price`

### Probe results

**Probe:** `.bobreviewer/probes/invoice_basic.json` — `invoice.calculate_invoice`

| Case | Before | After | Status | Decision |
|---|---|---|---|---|
| `invoice-small-discount` | `100.0` | `99.99` | ⚠️ Behavior differs | **Unintended** — Invoices must round to cents; flooring loses a cent (proposed — approved when merged) |

> A difference with no decision yet is unresolved work, not an approval.

### Analysis and execution notes

- Python interpreter: python3.11
- Ran with bobreviewer's own Python; install the project's dependencies there or create .venv

### Test results

| Test | Base | Head |
|---|---|---|
| `tests/test_discount.py::TestApplyDiscount::test_fifty_percent` | ✅ Pass | ✅ Pass |
| `tests/test_discount.py::TestApplyDiscount::test_no_discount` | ✅ Pass | ✅ Pass |
| `tests/test_discount.py::TestApplyDiscount::test_result_is_float` | ✅ Pass | ✅ Pass |
| `tests/test_discount.py::TestApplyDiscount::test_zero_price` | ✅ Pass | ✅ Pass |
| `tests/test_discount.py::TestCalculateInvoice::test_fifty_percent` | ✅ Pass | ✅ Pass |
| `tests/test_discount.py::TestCalculateInvoice::test_no_discount` | ✅ Pass | ✅ Pass |
