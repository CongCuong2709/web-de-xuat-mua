import mimetypes
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Department
from core.models import AppSettings, ReturnReason

from . import attachments
from . import payments as pm
from . import workflow as wf
from .forms import initial_from, parse_proposal
from .models import ApprovalLog, Attachment, PaymentRequest, Proposal

S = Proposal.Status

GROUPS = [
    ("", "Tất cả", None),
    ("cho", "Đang chờ duyệt", Q(status__in=Proposal.PENDING)),
    ("tra_ve", "Bị trả về", Q(status=S.TRA_VE)),
    ("da_duyet", "Đang mua / chi tiền", Q(status=S.DA_DUYET)),
    ("hoan_thanh", "Hoàn thành", Q(status=S.HOAN_THANH)),
    ("da_huy", "Đã hủy", Q(status=S.DA_HUY)),
]


def _with_relations(qs):
    return qs.select_related("creator", "department", "manager").prefetch_related(
        Prefetch("logs", queryset=ApprovalLog.objects.select_related("actor", "payment")),
        Prefetch("payments", queryset=PaymentRequest.objects.select_related("requester")),
    )


def _get_visible(user, code):
    p = _with_relations(wf.visible_proposals(user)).filter(code=code).first()
    if not p:
        raise Http404
    return p


def _payments_with_relations(qs):
    return qs.select_related("proposal", "proposal__department", "requester").prefetch_related(
        Prefetch("logs", queryset=ApprovalLog.objects.select_related("actor", "payment"))
    )


@login_required
def home(request):
    user = request.user
    props = _with_relations(Proposal.objects.filter(wf.pending_q(user)))
    pays = _payments_with_relations(PaymentRequest.objects.filter(pm.pending_q(user)))
    cards = [{"type": "mua", "obj": p, "at": p.updated_at} for p in props]
    cards += [{"type": "tam_ung" if x.is_advance else "thanh_toan", "obj": x, "at": x.updated_at} for x in pays]
    cards.sort(key=lambda c: c["at"], reverse=True)
    types = {c["type"] for c in cards}
    return render(request, "proposals/home.html", {"cards": cards, "types": types, "show_tabs": len(types) > 1})


@login_required
def detail(request, code):
    p = _get_visible(request.user, code)
    ctx = {
        "p": p,
        "actions": wf.actions_for(request.user, p),
        "steps": wf.timeline(p, request.user),
        "reasons": ReturnReason.objects.filter(is_active=True),
        "threshold": AppSettings.load().chairman_threshold,
        "items": list(p.items.all()),
        "files": list(p.attachments.filter(payment__isnull=True)),
        "payments": list(p.payments.all()),
    }
    if request.GET.get("pane"):
        return render(request, "proposals/_detail.html", ctx)
    return render(request, "proposals/detail.html", ctx)


@login_required
@require_POST
def act(request, code):
    p = _get_visible(request.user, code)
    action = request.POST.get("action")
    try:
        if action == wf.APPROVE:
            wf.approve(request.user, p, request.POST.get("note", ""))
            messages.success(request, f"Đã duyệt {p.code}.")
        elif action == wf.RETURN:
            wf.return_(request.user, p, return_reason(request.POST))
            messages.success(request, f"Đã trả về {p.code} cho {p.creator}.")
        elif action == wf.CANCEL:
            wf.cancel(request.user, p)
            messages.success(request, f"Đã hủy {p.code}.")
        else:
            return HttpResponseForbidden("Thao tác không hợp lệ.")
    except wf.WorkflowError as e:
        messages.error(request, str(e))
        return redirect("proposal_detail", code=p.code)
    return redirect("home")


def return_reason(post):
    parts = [post.get("reason_choice", "").strip(), post.get("note", "").strip()]
    return ". ".join(x for x in parts if x)


def _form(request, p=None):
    if p is None and not wf.can_create(request.user):
        return HttpResponseForbidden("Bạn không có quyền tạo đề xuất.")
    errors = []
    if request.method == "POST":
        data, errors = parse_proposal(request.POST)
        files = request.FILES.getlist("files")
        errors += attachments.validate(files)
        if not errors:
            try:
                if p is None:
                    p = wf.create(request.user, data["title"], data["reason"], data["items"], files)
                    messages.success(request, f"Đã gửi {p.code} cho trưởng phòng duyệt.")
                    return redirect("home")
                remove = [int(x) for x in request.POST.getlist("remove_file") if x.isdigit()]
                p = wf.resubmit(request.user, p, data["title"], data["reason"], data["items"], files, remove)
                messages.success(request, f"Đã gửi lại {p.code}.")
                return redirect("proposal_detail", code=p.code)
            except wf.WorkflowError as e:
                errors = [str(e)]
    else:
        data = initial_from(p) if p else {"title": "", "reason": "", "raw_items": [{"name": "", "qty": "1", "price": ""}]}
    returned = None
    if p is not None:
        returned = next((log for log in reversed(p.logs.all())
                         if log.action == ApprovalLog.Action.RETURN and not log.payment_id), None)
    return render(request, "proposals/form.html", {
        "p": p,
        "data": data,
        "errors": errors,
        "returned": returned,
        "threshold": AppSettings.load().chairman_threshold,
        "has_manager": bool(request.user.manager_id),
        "files": list(p.attachments.filter(payment__isnull=True)) if p else [],
        "accept": attachments.ACCEPT,
    })


@login_required
def create(request):
    return _form(request)


@login_required
def edit(request, code):
    p = _get_visible(request.user, code)
    if wf.EDIT not in wf.actions_for(request.user, p):
        messages.error(request, "Đề xuất này không ở trạng thái sửa được.")
        return redirect("proposal_detail", code=code)
    return _form(request, p)


@login_required
def proposal_list(request):
    qs = _with_relations(wf.visible_proposals(request.user))
    q = request.GET.get("q", "").strip()
    group = request.GET.get("nhom", "")
    dept = request.GET.get("phong", "")
    if q:
        qs = qs.filter(
            Q(code__icontains=q) | Q(title__icontains=q) | Q(creator__full_name__icontains=q)
            | Q(creator__username__icontains=q) | Q(items__name__icontains=q)
        ).distinct()
    cond = dict((k, c) for k, _, c in GROUPS).get(group)
    if cond is not None:
        qs = qs.filter(cond)
    if dept.isdigit():
        qs = qs.filter(department_id=int(dept))
    page = Paginator(qs.order_by("-updated_at"), 50).get_page(request.GET.get("trang"))
    params = request.GET.copy()
    params.pop("trang", None)
    ctx = {
        "page": page,
        "q": q,
        "group": group,
        "dept": dept,
        "groups": [(k, label) for k, label, _ in GROUPS],
        "departments": Department.objects.all(),
        "querystring": params.urlencode(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "proposals/_table.html", ctx)
    return render(request, "proposals/list.html", ctx)


@login_required
def attachment(request, pk):
    """Tải file đính kèm: chỉ người xem được đề xuất mới tải được."""
    att = get_object_or_404(Attachment, pk=pk)
    if not wf.visible_proposals(request.user).filter(pk=att.proposal_id).exists():
        raise Http404
    ext = os.path.splitext(att.file.name)[1].lower()
    ctype = mimetypes.guess_type(att.file.name)[0] or "application/octet-stream"
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    return FileResponse(fh, content_type=ctype, as_attachment=ext not in attachments.INLINE, filename=att.name)
