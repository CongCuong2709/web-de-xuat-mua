from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def vnd(value):
    """18500000 -> '18.500.000'. Rỗng -> '—'."""
    if value is None or value == "":
        return "—"
    return f"{int(round(Decimal(value))):,}".replace(",", ".")


@register.filter
def qty(value):
    """Decimal('2.00') -> '2', Decimal('2.50') -> '2,5'."""
    if value is None:
        return ""
    return f"{Decimal(value).normalize():f}".replace(".", ",")
