"""Đọc dữ liệu form tạo/sửa đề xuất. Danh sách món gửi lên dạng mảng:
item_name[], item_qty[], item_price[] (giao diện do Alpine quản lý số dòng).
"""
import re
from decimal import Decimal, InvalidOperation
from itertools import zip_longest

MAX_ITEMS = 50


def _money(raw):
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else None


def _qty(raw):
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return Decimal(1)
    try:
        q = Decimal(raw)
    except InvalidOperation:
        return None
    return q if 0 < q < Decimal("100000000") else None


def parse_proposal(post):
    """Trả về (data, errors). data dùng để gọi workflow và để vẽ lại form khi có lỗi."""
    errors = []
    rows = zip_longest(post.getlist("item_name"), post.getlist("item_qty"), post.getlist("item_price"), fillvalue="")
    items, raw_items = [], []
    for i, (name, qty, price) in enumerate(rows, start=1):
        name = name.strip()
        raw_items.append({"name": name, "qty": qty.strip(), "price": price.strip()})
        if not name and not price.strip():
            continue  # dòng trống
        q = _qty(qty)
        if not name:
            errors.append(f"Dòng {i}: thiếu tên món.")
        if q is None:
            errors.append(f"Dòng {i}: số lượng không hợp lệ.")
        if name and q is not None:
            items.append({"name": name[:200], "quantity": q, "unit_price": _money(price)})
    if len(items) > MAX_ITEMS:
        errors.append(f"Tối đa {MAX_ITEMS} món một đề xuất.")
    data = {
        "title": post.get("title", "").strip()[:200],
        "reason": post.get("reason", "").strip(),
        "items": items,
        "raw_items": [r for r in raw_items if r["name"] or r["price"]] or [{"name": "", "qty": "1", "price": ""}],
    }
    if not data["title"]:
        errors.append("Cần ghi rõ cần mua gì.")
    if not data["reason"]:
        errors.append("Cần ghi lý do, mục đích.")
    if not items and not errors:
        errors.append("Cần ít nhất một món.")
    return data, errors


def initial_from(p):
    return {
        "title": p.title,
        "reason": p.reason,
        "raw_items": [
            {"name": it.name, "qty": f"{it.quantity.normalize():f}", "price": str(it.unit_price or "")}
            for it in p.items.all()
        ],
    }
