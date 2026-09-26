"""invoice.py — sample project module (unchanged across all demo tags)."""

from discount import apply_discount


def calculate_invoice(price: float, discount_rate: float) -> float:
    """Calculate the final invoice amount after applying discount."""
    return apply_discount(price, discount_rate)
