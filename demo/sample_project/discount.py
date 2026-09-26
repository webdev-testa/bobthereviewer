"""
discount.py — sample project module (demo-base version)

Uses round(..., 2) which, for a very small discount rate, rounds up
to the next cent (e.g. 99.999... -> 100.0).
"""


def apply_discount(price: float, discount_rate: float) -> float:
    """Return price after applying discount_rate (0.0 – 1.0), rounded to 2 d.p."""
    return round(price * (1 - discount_rate), 2)
