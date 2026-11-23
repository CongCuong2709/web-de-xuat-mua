"""Màn hình phiếu tạm ứng / thanh toán. Luật nằm ở payments.py."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.models import ReturnReason

from . import attachments
from . import payments as pm
from .forms import money
from .models import ApprovalLog, PaymentRequest
from .views import _get_visible, _payments_with_relations, return_reason
from .workflow import WorkflowError

PS = PaymentRequest.Status
K = PaymentRequest.Kind

KIND_SLUGS = {"tam-ung": K.TAM_UNG, "thanh-toan": K.THANH_TOAN}

GROUPS = [
    ("", "Tất cả", None),
    ("cho", "Đang chờ duyệt", Q(status__in=[PS.CHO_CHU_TICH_UNG, PS.CHO_KE_TOAN, PS.CHO_CHU_TICH_CHI,
                                           PS.CHO_DUYET_HOAN_UNG])),
    ("chuyen", "Chờ chuyển tiền", Q(status=PS.CHO_CHUYEN_TIEN)),
    ("dang_mua", "Đang mua", Q(status=PS.DANG_MUA)),
    ("tra_ve", "Bị trả về", Q(status=PS.TRA_VE)),
    ("xong", "Hoàn tất", Q(status=PS.HOAN_TAT)),
    ("huy", "Đã hủy", Q(status=PS.DA_HUY)),
]


def _get_payment(user, code):
    pay = _payments_with_relations(pm.visible_payments(user)).filter(code=code).first()
    if not pay:
        raise Http404
    return pay


def _form_ctx(request, p, pay, kind, data, errors):
    returned = None
    if pay is not None:
        returned = next((log for log in reversed(pay.logs.all()) if log.action == ApprovalLog.Action.RETURN), None)
    return {
        "p": p, "pay": pay, "kind": kind, "data": data, "errors": errors, "returned": returned,
        "files": list(pay.attachments.all()) if pay else [],
        "accept": attachments.ACCEPT,
    }


@login_required
def payment_create(request, code):
    p = _get_visible(request.user, code)
    if not pm.can_request_money(request.user, p):
        messages.error(request, "Đề xuất này không ở trạng thái xin tiền được, hoặc đã có phiếu đang chạy.")
        return redirect("proposal_detail", code=code)
    kind = KIND_SLUGS.get(request.POST.get("loai") or request.GET.get("loai"), K.TAM_UNG)
    data = {"amount": str(p.total or ""), "note": ""}
    errors = []
    if request.method == "POST":
        data = {"amount": request.POST.get("amount", ""), "note": request.POST.get("note", "")}
        files = request.FILES.getlist("files")
        errors = attachments.validate(files)
        if not errors:
            try:
                pay = pm.create(request.user, p, kind, money(data["amount"]), data["note"], files)
                messages.success(request, f"Đã gửi {pay.code}.")
                return redirect("payment_detail", code=pay.code)
            except WorkflowError as e:
                errors = [str(e)]
    return render(request, "proposals/payment_form.html", _form_ctx(request, p, None, kind, data, errors))


@login_required
def payment_edit(request, code):
    pay = _get_payment(request.user, code)
    if pm.EDIT not in pm.actions_for(request.user, pay):
        messages.error(request, "Phiếu này không ở trạng thái sửa được.")
        return redirect("payment_detail", code=code)
    data = {"amount": str(pay.amount), "note": pay.note}
    errors = []
    if request.method == "POST":
        data = {"amount": request.POST.get("amount", ""), "note": request.POST.get("note", "")}
        files = request.FILES.getlist("files")
        errors = attachments.validate(files)
        if not errors:
            remove = [int(x) for x in request.POST.getlist("remove_file") if x.isdigit()]
            try:
                pm.resubmit(request.user, pay, money(data["amount"]), data["note"], files, remove)
                messages.success(request, f"Đã gửi lại {pay.code}.")
                return redirect("payment_detail", code=pay.code)
            except WorkflowError as e:
                errors = [str(e)]
    return render(request, "proposals/payment_form.html",
                  _form_ctx(request, pay.proposal, pay, pay.kind, data, errors))


@login_required
def payment_settle(request, code):
    pay = _get_payment(request.user, code)
    if pm.SETTLE not in pm.actions_for(request.user, pay):
        messages.error(request, "Phiếu này không ở bước đề nghị hoàn ứng.")
        return redirect("payment_detail", code=code)
    data = {"spent": str(pay.spent if pay.spent is not None else pay.amount), "note": ""}
    errors = []
    if request.method == "POST":
        data = {"spent": request.POST.get("spent", ""), "note": request.POST.get("note", "")}
        files = request.FILES.getlist("files")
        errors = attachments.validate(files)
        if not errors:
            remove = [int(x) for x in request.POST.getlist("remove_file") if x.isdigit()]
            try:
                pm.settle(request.user, pay, money(data["spent"]), data["note"], files, remove)
                messages.success(request, f"Đã gửi đề nghị hoàn ứng {pay.code}.")
                return redirect("home")
            except WorkflowError as e:
                errors = [str(e)]
    returned = next((log for log in reversed(pay.logs.all())
                     if log.action == ApprovalLog.Action.RETURN and log.from_status == PS.CHO_DUYET_HOAN_UNG), None)
    return render(request, "proposals/payment_settle.html", {
        "pay": pay, "data": data, "errors": errors, "returned": returned,
        "files": list(pay.attachments.filter(uploaded_by=request.user)),
        "accept": attachments.ACCEPT,
    })


@login_required
def payment_detail(request, code):
    pay = _get_payment(request.user, code)
    ctx = {
        "pay": pay,
        "p": pay.proposal,
        "actions": pm.actions_for(request.user, pay),
        "steps": pm.timeline(pay, request.user),
        "reasons": ReturnReason.objects.filter(is_active=True),
        "files": list(pay.attachments.select_related("uploaded_by")),
    }
    if request.GET.get("pane"):
        return render(request, "proposals/_payment_detail.html", ctx)
    return render(request, "proposals/payment_detail.html", ctx)


@login_required
@require_POST
def payment_act(request, code):
    pay = _get_payment(request.user, code)
    action = request.POST.get("action")
    note = request.POST.get("note", "")
    files = request.FILES.getlist("files")
    errs = attachments.validate(files)
    if errs:
        for e in errs:
            messages.error(request, e)
        return redirect("payment_detail", code=code)
    try:
        if action == pm.APPROVE:
            pm.approve(request.user, pay, note)
            messages.success(request, f"Đã duyệt {pay.code}.")
        elif action == pm.RETURN:
            pm.return_(request.user, pay, return_reason(request.POST))
            messages.success(request, f"Đã trả về {pay.code} cho {pay.requester}.")
        elif action == pm.TRANSFER:
            pm.transfer(request.user, pay, note, files)
            messages.success(request, f"Đã ghi nhận chuyển tiền {pay.code}.")
        elif action == pm.CANCEL:
            pm.cancel(request.user, pay)
            messages.success(request, f"Đã hủy {pay.code}.")
        else:
            return HttpResponseForbidden("Thao tác không hợp lệ.")
    except WorkflowError as e:
        messages.error(request, str(e))
        return redirect("payment_detail", code=code)
    return redirect("home")


@login_required
def payment_list(request):
    qs = _payments_with_relations(pm.visible_payments(request.user))
    q = request.GET.get("q", "").strip()
    group = request.GET.get("nhom", "")
    kind = request.GET.get("loai", "")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(proposal__code__icontains=q) | Q(proposal__title__icontains=q)
                       | Q(requester__full_name__icontains=q))
    cond = dict((k, c) for k, _, c in GROUPS).get(group)
    if cond is not None:
        qs = qs.filter(cond)
    if kind in K.values:
        qs = qs.filter(kind=kind)
    page = Paginator(qs.order_by("-updated_at"), 50).get_page(request.GET.get("trang"))
    params = request.GET.copy()
    params.pop("trang", None)
    ctx = {
        "page": page, "q": q, "group": group, "kind": kind,
        "groups": [(k, label) for k, label, _ in GROUPS],
        "kinds": K.choices,
        "querystring": params.urlencode(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "proposals/_payment_table.html", ctx)
    return render(request, "proposals/payment_list.html", ctx)
