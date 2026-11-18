"""Luật duyệt đề xuất: MỘT chỗ duy nhất.

Ai được làm gì, ở trạng thái nào, đi tiếp sang đâu. Mọi màn hình gọi vào đây,
không tự kiểm tra quyền riêng. Mỗi thao tác ghi một dòng ApprovalLog.

Luồng:
    Nhân viên tạo -> Trưởng phòng trực tiếp -> Giám đốc (1 trong 2 người)
        -> Chủ tịch (nếu tổng >= mốc cấu hình) -> Đã duyệt (thu mua mua hàng)
    Bất kỳ bước duyệt nào cũng có thể trả về (bắt buộc lý do) -> về người tạo
        -> sửa và gửi lại -> bắt đầu lại từ Trưởng phòng. Không giới hạn số lần.
    Người tạo được hủy khi đơn đang bị trả về hoặc trưởng phòng chưa xử lý.

Sau khi Đã duyệt: thu mua xin tạm ứng hoặc đề nghị thanh toán tự ứng. Luật phần tiền nằm
ở payments.py; đề xuất chuyển sang Hoàn thành khi phiếu tiền hoàn tất.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role
from core.models import AppSettings

from . import attachments
from .models import ApprovalLog, PaymentRequest, Proposal, ProposalItem

S = Proposal.Status
A = ApprovalLog.Action

APPROVE, RETURN, EDIT, CANCEL = "approve", "return", "edit", "cancel"
REQUEST_MONEY = "request_money"  # thu mua xin tạm ứng / đề nghị thanh toán

# Bước duyệt -> bước kế tiếp (Chủ tịch chỉ chen vào khi cần)
_ROLE_FOR_STEP = {S.CHO_GIAM_DOC: Role.GIAM_DOC, S.CHO_CHU_TICH: Role.CHU_TICH}


class WorkflowError(Exception):
    """Thao tác không hợp lệ: sai người, sai trạng thái, thiếu dữ liệu."""


# ---------- Hỏi quyền ----------

def can_create(user):
    return user.is_authenticated and user.has_role(Role.NHAN_VIEN)


def is_approver(user, p):
    if p.status == S.CHO_TRUONG_PHONG:
        return p.manager_id == user.pk
    role = _ROLE_FOR_STEP.get(p.status)
    return bool(role) and user.has_role(role)


def _has_active_payment(p):
    return p.payments.exclude(status=PaymentRequest.Status.DA_HUY).exists()


def can_request_money(user, p):
    return p.status == S.DA_DUYET and user.has_role(Role.THU_MUA) and not _has_active_payment(p)


def actions_for(user, p):
    acts = []
    if is_approver(user, p):
        acts += [APPROVE, RETURN]
    if can_request_money(user, p):
        acts.append(REQUEST_MONEY)
    if p.creator_id == user.pk:
        if p.status == S.TRA_VE:
            acts += [EDIT, CANCEL]
        elif p.status == S.CHO_TRUONG_PHONG:
            acts += [CANCEL]
    return acts


def pending_q(user):
    """Đơn đang chờ chính người này xử lý."""
    q = Q(status=S.TRA_VE, creator=user) | Q(status=S.CHO_TRUONG_PHONG, manager=user)
    if user.has_role(Role.GIAM_DOC):
        q |= Q(status=S.CHO_GIAM_DOC)
    if user.has_role(Role.CHU_TICH):
        q |= Q(status=S.CHO_CHU_TICH)
    if user.has_role(Role.THU_MUA):
        # Đơn đã duyệt mà chưa có phiếu tiền nào đang chạy: thu mua cần đi mua
        active = PaymentRequest.objects.exclude(status=PaymentRequest.Status.DA_HUY).values("proposal_id")
        q |= Q(status=S.DA_DUYET) & ~Q(pk__in=active)
    return q


def visible_q(user):
    """Đơn người này được xem. Lãnh đạo, kế toán, thu mua xem tất cả."""
    if user.is_superuser or user.has_role(Role.GIAM_DOC, Role.CHU_TICH, Role.KE_TOAN, Role.THU_MUA):
        return Q()
    q = Q(creator=user) | Q(manager=user) | Q(logs__actor=user)
    if user.has_role(Role.TRUONG_PHONG) and user.department_id:
        q |= Q(department_id=user.department_id)
    return q


def visible_proposals(user):
    return Proposal.objects.filter(visible_q(user)).distinct()


# ---------- Tiến trình để hiển thị ----------

def timeline(p, viewer=None):
    """Các bước đã qua (done/back), bước hiện tại (now) và bước sắp tới (todo)."""
    steps = []
    for log in p.logs.all():
        steps.append({
            "state": "back" if log.action in (A.RETURN, A.CANCEL) else "done",
            "title": log.sentence,
            "at": log.created_at,
            "note": log.note,
        })

    mine = viewer is not None and bool(actions_for(viewer, p))
    now_meta = "Đang chờ bạn" if mine else "Đang chờ"
    plan = [(S.CHO_TRUONG_PHONG, f"Trưởng phòng {p.manager or ''} duyệt".replace("  ", " ")),
            (S.CHO_GIAM_DOC, "Giám đốc duyệt")]
    if p.needs_chairman:
        plan.append((S.CHO_CHU_TICH, "Chủ tịch duyệt"))

    if p.status in Proposal.PENDING:
        idx = [s for s, _ in plan].index(p.status)
        for i, (_, title) in enumerate(plan[idx:]):
            steps.append({"state": "now" if i == 0 else "todo", "title": title, "meta": now_meta if i == 0 else ""})
        steps.append({"state": "todo", "title": "Thu mua mua hàng", "meta": "Bước tiếp theo" if idx == len(plan) - 1 else ""})
    elif p.status == S.TRA_VE:
        steps.append({"state": "now", "title": f"{p.creator} sửa và gửi lại", "meta": now_meta})
    elif p.status == S.DA_DUYET:
        pay = p.active_payment
        if pay is None:
            steps.append({"state": "now", "title": "Thu mua mua hàng, xin tạm ứng hoặc đề nghị thanh toán",
                          "meta": now_meta})
        else:
            from .payments import upcoming  # tránh import vòng
            steps += upcoming(pay, viewer)
    return steps


# ---------- Thao tác ----------

def next_code(model, kind="MS"):
    """Mã bất biến dạng KIND-YYYYMM-NNNN, đánh số lại mỗi tháng. Gọi trong transaction."""
    prefix = timezone.localtime().strftime(f"{kind}-%Y%m-")
    last = model.objects.filter(code__startswith=prefix).order_by("-code").values_list("code", flat=True).first()
    n = int(last[-4:]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def _save_content(p, title, reason, items, user=None, files=(), remove_ids=()):
    title, reason = (title or "").strip(), (reason or "").strip()
    if not title:
        raise WorkflowError("Cần ghi rõ cần mua gì.")
    if not reason:
        raise WorkflowError("Cần ghi lý do, mục đích.")
    if not items:
        raise WorkflowError("Cần ít nhất một món.")
    p.title, p.reason = title, reason
    p.total = sum(round(it["quantity"] * it["unit_price"]) for it in items if it.get("unit_price") is not None)
    p.needs_chairman = p.total >= AppSettings.load().chairman_threshold
    p.manager = p.creator.manager
    p.department = p.creator.department
    p.status = S.CHO_TRUONG_PHONG
    p.updated_at = timezone.now()
    p.save()
    p.items.all().delete()
    ProposalItem.objects.bulk_create(
        ProposalItem(proposal=p, order=i, name=it["name"], quantity=it["quantity"], unit_price=it.get("unit_price"))
        for i, it in enumerate(items)
    )
    attachments.remove(remove_ids, p)
    if files:
        attachments.save(files, user, p)


def _log(p, user, action, from_status, note=""):
    ApprovalLog.objects.create(
        proposal=p, actor=user, action=action, from_status=from_status, to_status=p.status, note=note,
        created_at=p.updated_at,
    )


def _reload(p):
    # Đọc lại trong transaction: hai giám đốc bấm cùng lúc thì người sau thấy trạng thái mới.
    return Proposal.objects.select_related("creator", "manager").get(pk=p.pk)


@transaction.atomic
def create(user, title, reason, items, files=()):
    if not can_create(user):
        raise WorkflowError("Bạn không có quyền tạo đề xuất.")
    if not user.manager_id:
        raise WorkflowError("Bạn chưa có trưởng phòng trực tiếp. Hãy báo quản trị viên.")
    p = Proposal(code=next_code(Proposal), creator=user)
    _save_content(p, title, reason, items, user, files)
    _log(p, user, A.SUBMIT, "")
    return p


@transaction.atomic
def resubmit(user, p, title, reason, items, files=(), remove_ids=()):
    p = _reload(p)
    if EDIT not in actions_for(user, p):
        raise WorkflowError("Đề xuất này không ở trạng thái sửa được.")
    if not user.manager_id:
        raise WorkflowError("Bạn chưa có trưởng phòng trực tiếp. Hãy báo quản trị viên.")
    before = p.status
    _save_content(p, title, reason, items, user, files, remove_ids)
    _log(p, user, A.RESUBMIT, before)
    return p


@transaction.atomic
def approve(user, p, note=""):
    p = _reload(p)
    if not is_approver(user, p):
        raise WorkflowError("Đề xuất này không còn chờ bạn duyệt.")
    before = p.status
    if before == S.CHO_TRUONG_PHONG:
        p.status = S.CHO_GIAM_DOC
    elif before == S.CHO_GIAM_DOC:
        p.status = S.CHO_CHU_TICH if p.needs_chairman else S.DA_DUYET
    else:
        p.status = S.DA_DUYET
    p.updated_at = timezone.now()
    p.save(update_fields=["status", "updated_at"])
    _log(p, user, A.APPROVE, before, (note or "").strip())
    return p


@transaction.atomic
def return_(user, p, reason):
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("Phải có lý do trả về.")
    p = _reload(p)
    if not is_approver(user, p):
        raise WorkflowError("Đề xuất này không còn chờ bạn duyệt.")
    before = p.status
    p.status = S.TRA_VE
    p.updated_at = timezone.now()
    p.save(update_fields=["status", "updated_at"])
    _log(p, user, A.RETURN, before, reason)
    return p


@transaction.atomic
def cancel(user, p, note=""):
    p = _reload(p)
    if CANCEL not in actions_for(user, p):
        raise WorkflowError("Không thể hủy đề xuất này.")
    before = p.status
    p.status = S.DA_HUY
    p.updated_at = timezone.now()
    p.save(update_fields=["status", "updated_at"])
    _log(p, user, A.CANCEL, before, (note or "").strip())
    return p
