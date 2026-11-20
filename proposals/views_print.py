"""Văn bản in A4 theo thể thức Nghị định 30. Người dùng bấm In / Lưu PDF trên trình duyệt."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from core.models import AppSettings

from . import printing
from .views import _get_visible
from .views_money import _get_payment


def _base_ctx(request, number, issued_at, back_url):
    cfg = AppSettings.load()
    return {
        "cfg": cfg,
        "number": number,
        "date_line": printing.ngay_thang(issued_at),
        "printed_at": timezone.now(),
        "back_url": back_url,
        "missing_org": not cfg.org_name or not cfg.place_name,
    }


@login_required
def print_proposal(request, code):
    p = _get_visible(request.user, code)
    sigs, issued_at = printing.proposal_signatures(p)
    ctx = _base_ctx(request, p.code, issued_at, request.build_absolute_uri(f"/de-xuat/{p.code}/"))
    ctx.update({
        "p": p,
        "items": list(p.items.all()),
        "sigs": sigs,
        "total_words": printing.so_thanh_chu(p.total),
        "dept": printing.department_phrase(p.department),
        "final": p.status in (p.Status.DA_DUYET, p.Status.HOAN_THANH),
    })
    return render(request, "print/proposal.html", ctx)


@login_required
def print_payment(request, code):
    pay = _get_payment(request.user, code)
    settlement = pay.is_advance and pay.spent is not None and request.GET.get("loai") != "tam-ung"
    sigs, issued_at = printing.payment_signatures(pay, settlement=settlement)
    ctx = _base_ctx(request, pay.code, issued_at, request.build_absolute_uri(f"/tien/{pay.code}/"))
    amount = pay.spent if settlement else pay.amount
    ctx.update({
        "pay": pay,
        "p": pay.proposal,
        "settlement": settlement,
        "sigs": sigs,
        "amount": amount,
        "amount_words": printing.so_thanh_chu(amount),
        "files": list(pay.attachments.all()),
        "final": pay.status == pay.Status.HOAN_TAT
        or (pay.is_advance and not settlement and pay.status not in (pay.Status.CHO_CHU_TICH_UNG, pay.Status.TRA_VE,
                                                                       pay.Status.DA_HUY)),
    })
    return render(request, "print/payment.html", ctx)
