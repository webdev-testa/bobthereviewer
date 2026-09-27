"""pricing.py — sample project module for tax scenarios."""

TAX_RATE = 0.10  # 10%


def calculate_price(base_price: float) -> float:
    """Return base_price with tax applied."""
    return round(base_price * (1 + TAX_RATE), 2)
