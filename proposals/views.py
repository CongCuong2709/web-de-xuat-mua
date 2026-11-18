from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Department
from core.models import AppSettings, ReturnReason

from . import workflow as wf
from .forms import initial_from, parse_proposal
from .models import ApprovalLog, Proposal

S = Proposal.Status

GROUPS = [
    ("", "Tất cả", None),
    ("cho", "Đang chờ duyệt", Q(status__in=Proposal.PENDING)),
    ("tra_ve", "Bị trả về", Q(status=S.TRA_VE)),
    ("da_duyet", "Đã duyệt", Q(status=S.DA_DUYET)),
    ("da_huy", "Đã hủy", Q(status=S.DA_HUY)),
]


def _with_relations(qs):
    return qs.select_related("creator", "department", "manager").prefetch_related(
        Prefetch("logs", queryset=ApprovalLog.objects.select_related("actor"))
    )


def _get_visible(user, code):
    p = _with_relations(wf.visible_proposals(user)).filter(code=code).first()
    if not p:
        raise Http404
    return p


@login_required
def home(request):
    items = _with_relations(Proposal.objects.filter(wf.pending_q(request.user))).order_by("-updated_at")
    return render(request, "proposals/home.html", {"items": items})


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
            parts = [request.POST.get("reason_choice", "").strip(), request.POST.get("note", "").strip()]
            wf.return_(request.user, p, ". ".join(x for x in parts if x))
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


def _form(request, p=None):
    if p is None and not wf.can_create(request.user):
        return HttpResponseForbidden("Bạn không có quyền tạo đề xuất.")
    errors = []
    if request.method == "POST":
        data, errors = parse_proposal(request.POST)
        if not errors:
            try:
                if p is None:
                    p = wf.create(request.user, data["title"], data["reason"], data["items"])
                    messages.success(request, f"Đã gửi {p.code} cho trưởng phòng duyệt.")
                    return redirect("home")
                p = wf.resubmit(request.user, p, data["title"], data["reason"], data["items"])
                messages.success(request, f"Đã gửi lại {p.code}.")
                return redirect("proposal_detail", code=p.code)
            except wf.WorkflowError as e:
                errors = [str(e)]
    else:
        data = initial_from(p) if p else {"title": "", "reason": "", "raw_items": [{"name": "", "qty": "1", "price": ""}]}
    returned = None
    if p is not None:
        returned = next((log for log in reversed(p.logs.all()) if log.action == ApprovalLog.Action.RETURN), None)
    return render(request, "proposals/form.html", {
        "p": p,
        "data": data,
        "errors": errors,
        "returned": returned,
        "threshold": AppSettings.load().chairman_threshold,
        "has_manager": bool(request.user.manager_id),
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
