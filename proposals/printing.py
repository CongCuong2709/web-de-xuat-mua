"""Dữ liệu cho văn bản in theo thể thức Nghị định 30/2020/NĐ-CP.

Phần trình bày (khổ A4, lề, phông, cỡ chữ) nằm ở templates/print/base.html.
Ở đây chỉ có: đọc số tiền thành chữ, ghi ngày đúng thể thức, và gom các chữ ký
(ai đã duyệt, lúc nào) từ lịch sử duyệt.
"""
from django.utils import timezone

from accounts.models import Role

from .models import ApprovalLog, PaymentRequest, Proposal

A = ApprovalLog.Action
PS = PaymentRequest.Status
S = Proposal.Status

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _read3(n, full):
    """Đọc nhóm 3 chữ số. full=True: đọc đủ 'không trăm', 'linh' (nhóm không đứng đầu)."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    words = []
    if h or full:
        words += [_DIGITS[h], "trăm"]
    if t == 0:
        if u and (h or full):
            words.append("linh")
    elif t == 1:
        words.append("mười")
    else:
        words += [_DIGITS[t], "mươi"]
    if u:
        if u == 1 and t > 1:
            words.append("mốt")
        elif u == 5 and t > 0:
            words.append("lăm")
        else:
            words.append(_DIGITS[u])
    return words


def _below_billion(n, full):
    words, started = [], full
    for g, unit in ((n // 10**6, "triệu"), (n // 1000 % 1000, "nghìn"), (n % 1000, "")):
        if g == 0:
            continue
        words += _read3(g, full=started)
        if unit:
            words.append(unit)
        started = True
    return words


def _read(n, full=False):
    if n >= 10**9:
        hi, lo = divmod(n, 10**9)
        words = _read(hi, full) + ["tỷ"]
        return words + (_below_billion(lo, True) if lo else [])
    return _below_billion(n, full)


def so_thanh_chu(amount):
    """18500000 -> 'Mười tám triệu năm trăm nghìn đồng'."""
    n = int(amount or 0)
    if n <= 0:
        return "Không đồng"
    text = " ".join(_read(n))
    return text[0].upper() + text[1:] + " đồng"


def ngay_thang(dt):
    """Ngày tháng theo NĐ30: ngày < 10 và tháng 1, 2 thêm số 0 phía trước."""
    if dt is None:
        return "ngày ..... tháng ..... năm ......."
    d = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    day = f"{d.day:02d}"
    month = f"{d.month:02d}" if d.month <= 2 else str(d.month)
    return f"ngày {day} tháng {month} năm {d.year}"


def _sig(title, user=None, at=None, note="", verb="duyệt"):
    return {"title": title, "user": user, "at": at, "note": note, "verb": verb}


def department_phrase(dept):
    """'Kỹ thuật' -> 'Phòng Kỹ thuật'; giữ nguyên nếu tên đã là 'Phòng ...', 'Ban ...', 'Bộ phận ...'."""
    name = str(dept or "").strip()
    if not name:
        return "Bộ phận"
    if name.lower().startswith(("phòng", "ban ", "bộ phận", "tổ ", "trung tâm")):
        return name
    return f"Phòng {name}"


def _last(logs, pred):
    found = None
    for log in logs:
        if pred(log):
            found = log
    return found


def proposal_signatures(p):
    """Người đề xuất, Trưởng phòng, Giám đốc, (Chủ tịch). Chỉ tính lượt gửi gần nhất."""
    logs = [l for l in p.logs.all() if l.payment_id is None]
    start = _last(logs, lambda l: l.action in (A.SUBMIT, A.RESUBMIT))
    after = logs[logs.index(start):] if start else []

    def approved(step):
        return _last(after, lambda l: l.action == A.APPROVE and l.from_status == step)

    tp, gd = approved(S.CHO_TRUONG_PHONG), approved(S.CHO_GIAM_DOC)
    if tp and tp.to_status != S.CHO_GIAM_DOC:
        # Giám đốc kiêm Trưởng phòng duyệt gộp 1 bước: chỉ hiện 1 chữ ký Giám đốc
        sigs = [
            _sig("Người đề xuất", p.creator, start.created_at if start else None, verb="gửi"),
            _sig("Giám đốc", tp.actor, tp.created_at, tp.note),
        ]
    elif not tp and p.manager and p.manager.has_role(Role.GIAM_DOC):
        sigs = [
            _sig("Người đề xuất", p.creator, start.created_at if start else None, verb="gửi"),
            _sig("Giám đốc", p.manager, None),
        ]
    else:
        sigs = [
            _sig("Người đề xuất", p.creator, start.created_at if start else None, verb="gửi"),
            _sig("Trưởng phòng", tp.actor if tp else p.manager, tp.created_at if tp else None, tp.note if tp else ""),
            _sig("Giám đốc", gd.actor if gd else None, gd.created_at if gd else None, gd.note if gd else ""),
        ]
    if p.needs_chairman:
        ct = approved(S.CHO_CHU_TICH)
        sigs.append(_sig("Chủ tịch", ct.actor if ct else None, ct.created_at if ct else None, ct.note if ct else ""))
    return sigs, (start.created_at if start else p.created_at)


def payment_signatures(pay, settlement=False):
    """Giấy tạm ứng / thanh toán: Người đề nghị, Kế toán, Chủ tịch.
    settlement=True: giấy thanh toán tạm ứng (hoàn ứng)."""
    logs = list(pay.logs.all())
    if settlement:
        start = _last(logs, lambda l: l.action == A.SETTLE)
        after = logs[logs.index(start):] if start else []
        ct = _last(after, lambda l: l.action == A.APPROVE and l.from_status == PS.CHO_DUYET_HOAN_UNG)
        kt = _last(logs, lambda l: l.action == A.TRANSFER)
        sigs = [
            _sig("Người đề nghị", pay.requester, start.created_at if start else None, verb="gửi"),
            _sig("Kế toán", kt.actor if kt else None, kt.created_at if kt else None, verb="chuyển tạm ứng"),
            _sig("Chủ tịch", ct.actor if ct else None, ct.created_at if ct else None, ct.note if ct else ""),
        ]
        return sigs, (start.created_at if start else None)

    start = _last(logs, lambda l: l.action in (A.SUBMIT, A.RESUBMIT))
    after = logs[logs.index(start):] if start else []
    if pay.is_advance:
        ct = _last(after, lambda l: l.action == A.APPROVE and l.from_status == PS.CHO_CHU_TICH_UNG)
        kt = _last(after, lambda l: l.action == A.TRANSFER)
        kt_label = "chuyển tiền"
    else:
        kt = _last(after, lambda l: l.action == A.APPROVE and l.from_status == PS.CHO_KE_TOAN)
        ct = _last(after, lambda l: l.action == A.APPROVE and l.from_status == PS.CHO_CHU_TICH_CHI)
        kt_label = "duyệt"
    sigs = [
        _sig("Người đề nghị", pay.requester, start.created_at if start else None, verb="gửi"),
        _sig("Kế toán", kt.actor if kt else None, kt.created_at if kt else None, kt.note if kt else "", verb=kt_label),
        _sig("Chủ tịch", ct.actor if ct else None, ct.created_at if ct else None, ct.note if ct else ""),
    ]
    return sigs, (start.created_at if start else pay.created_at)
