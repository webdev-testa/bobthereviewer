"""Tests for the sample project — pass on both demo-base and demo-rounding-change."""

import sys
import os

# Allow running from the sample project directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from discount import apply_discount
from invoice import calculate_invoice


class TestApplyDiscount:
    def test_no_discount(self):
        # 0% discount — result must be exactly the original price
        assert apply_discount(100.0, 0.0) == 100.0

    def test_fifty_percent(self):
        # 50% discount — passes on both rounding versions
        assert apply_discount(200.0, 0.5) == 100.0

    def test_zero_price(self):
        assert apply_discount(0.0, 0.5) == 0.0

    def test_result_is_float(self):
        result = apply_discount(99.0, 0.1)
        assert isinstance(result, float)


class TestCalculateInvoice:
    def test_no_discount(self):
        assert calculate_invoice(100.0, 0.0) == 100.0

    def test_fifty_percent(self):
        assert calculate_invoice(200.0, 0.5) == 100.0
