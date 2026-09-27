"""
discount.py — sample project module (demo-rounding-change version)

Changed: apply_discount now truncates to 2 decimal places using floor
instead of rounding.  This is a subtle behavioural difference that passes
all existing tests (which only test 0% and 50% discounts) but changes the
result for tiny discount rates.

  demo-base:            round(99.999..., 2)  = 100.0
  demo-rounding-change: floor(99.999...*100)/100 = 99.99
"""

import math


def apply_discount(price: float, discount_rate: float) -> float:
    """Return price after applying discount_rate (0.0 – 1.0), truncated to 2 d.p."""
    return math.floor(price * (1 - discount_rate) * 100) / 100
