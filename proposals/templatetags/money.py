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


@register.filter
def lowerfirst(value):
    """'Laptop cho phòng KT' -> 'laptop cho phòng KT'; giữ nguyên chữ viết tắt như 'HP', 'USB'."""
    s = str(value or "")
    if len(s) > 1 and s[0].isupper() and s[1].islower():
        return s[0].lower() + s[1:]
    return s
