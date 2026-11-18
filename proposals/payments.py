"""Luật luồng tiền: MỘT chỗ duy nhất cho phiếu tạm ứng / thanh toán.

Mọi khoản tiền đều do Chủ tịch duyệt chi, tiền luôn về tài khoản thu mua (không chuyển thẳng
nhà cung cấp). Mỗi đề xuất chỉ có một phiếu đang chạy; hủy phiếu thì được lập phiếu mới.

Tạm ứng (TU):
    Thu mua xin -> Chủ tịch duyệt -> Kế toán chuyển tiền -> Thu mua mua hàng, đề nghị hoàn ứng
    (ghi số thực chi, kèm hóa đơn nếu có) -> Chủ tịch duyệt hoàn ứng -> Hoàn tất.
    Chủ tịch trả về đề nghị hoàn ứng thì phiếu quay lại bước "đang mua" để thu mua gửi lại.
Thanh toán tự ứng (TT): thu mua đã mua bằng tiền mình, bắt buộc kèm hóa đơn
    -> Kế toán duyệt (đề xuất chi) -> Chủ tịch duyệt và hoàn tiền -> Hoàn tất.
Trả về ở bước duyệt phiếu (bắt buộc lý do) -> thu mua sửa và gửi lại, hoặc hủy phiếu.
Phiếu hoàn tất -> đề xuất chuyển sang Hoàn thành.
Thừa/thiếu khi quyết toán tạm ứng chỉ hiển thị, chưa có luồng xử lý riêng (để sau).
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role

from . import attachments
from .models import ApprovalLog, PaymentRequest, Proposal
from .workflow import WorkflowError, can_request_money, next_code, visible_q

PS = PaymentRequest.Status
K = PaymentRequest.Kind
A = ApprovalLog.Action

APPROVE, RETURN, TRANSFER, SETTLE, EDIT, CANCEL = "approve", "return", "transfer", "settle", "edit", "cancel"

# Bước duyệt: trạng thái -> (vai trò được làm, duyệt xong sang đâu, trả về thì về đâu)
_APPROVAL_STEPS = {
    PS.CHO_CHU_TICH_UNG: (Role.CHU_TICH, PS.CHO_CHUYEN_TIEN, PS.TRA_VE),
    PS.CHO_DUYET_HOAN_UNG: (Role.CHU_TICH, PS.HOAN_TAT, PS.DANG_MUA),
    PS.CHO_KE_TOAN: (Role.KE_TOAN, PS.CHO_CHU_TICH_CHI, PS.TRA_VE),
    PS.CHO_CHU_TICH_CHI: (Role.CHU_TICH, PS.HOAN_TAT, PS.TRA_VE),
}
_FIRST_STEP = {K.TAM_UNG: PS.CHO_CHU_TICH_UNG, K.THANH_TOAN: PS.CHO_KE_TOAN}
_CODE_PREFIX = {K.TAM_UNG: "TU", K.THANH_TOAN: "TT"}
ACTIVE = [s for s in PS.values if s not in (PS.HOAN_TAT, PS.DA_HUY)]


# ---------- Hỏi quyền ----------

def actions_for(user, pay):
    acts = []
    step = _APPROVAL_STEPS.get(pay.status)
    if step and user.has_role(step[0]):
        acts += [APPROVE, RETURN]
    if pay.status == PS.CHO_CHUYEN_TIEN and user.has_role(Role.KE_TOAN):
        acts.append(TRANSFER)
    if pay.requester_id == user.pk:
        if pay.status == PS.DANG_MUA:
            acts.append(SETTLE)
        elif pay.status == PS.TRA_VE:
            acts += [EDIT, CANCEL]
        elif pay.status == _FIRST_STEP[pay.kind]:
            acts.append(CANCEL)
    return acts


def pending_q(user):
    q = Q(requester=user, status__in=[PS.DANG_MUA, PS.TRA_VE])
    for status, (role, _, _) in _APPROVAL_STEPS.items():
        if user.has_role(role):
            q |= Q(status=status)
    if user.has_role(Role.KE_TOAN):
        q |= Q(status=PS.CHO_CHUYEN_TIEN)
    return q


def visible_payments(user):
    """Ai xem được đề xuất thì xem được phiếu tiền của nó."""
    return PaymentRequest.objects.filter(proposal__in=Proposal.objects.filter(visible_q(user)))


def can_see_money_pages(user):
    return user.has_role(Role.THU_MUA, Role.KE_TOAN, Role.CHU_TICH, Role.GIAM_DOC)


# ---------- Tiến trình ----------

def _plan(pay):
    if pay.is_advance:
        return [
            (PS.CHO_CHU_TICH_UNG, "Chủ tịch duyệt tạm ứng"),
            (PS.CHO_CHUYEN_TIEN, "Kế toán chuyển tiền cho thu mua"),
            (PS.DANG_MUA, f"{pay.requester} mua hàng, đề nghị hoàn ứng"),
            (PS.CHO_DUYET_HOAN_UNG, "Chủ tịch duyệt hoàn ứng"),
        ]
    return [
        (PS.CHO_KE_TOAN, "Kế toán duyệt, đề xuất chi"),
        (PS.CHO_CHU_TICH_CHI, f"Chủ tịch duyệt và hoàn tiền cho {pay.requester}"),
    ]


def upcoming(pay, viewer=None):
    """Bước hiện tại và các bước còn lại của phiếu (dùng cả trong tiến trình đề xuất)."""
    mine = viewer is not None and bool(actions_for(viewer, pay))
    meta = "Đang chờ bạn" if mine else "Đang chờ"
    if pay.status == PS.TRA_VE:
        return [{"state": "now", "title": f"{pay.requester} sửa và gửi lại phiếu {pay.code}", "meta": meta}]
    plan = _plan(pay)
    codes = [s for s, _ in plan]
    if pay.status not in codes:
        return []
    idx = codes.index(pay.status)
    return [
        {"state": "now" if i == 0 else "todo", "title": title, "meta": meta if i == 0 else ""}
        for i, (_, title) in enumerate(plan[idx:])
    ]


def timeline(pay, viewer=None):
    steps = [
        {"state": "back" if log.action in (A.RETURN, A.CANCEL) else "done",
         "title": log.sentence, "at": log.created_at, "note": log.note}
        for log in pay.logs.all()
    ]
    return steps + upcoming(pay, viewer)


# ---------- Thao tác ----------

def _reload(pay):
    return PaymentRequest.objects.select_related("proposal", "requester").get(pk=pay.pk)


def _log(pay, user, action, before, note=""):
    ApprovalLog.objects.create(
        proposal_id=pay.proposal_id, payment=pay, actor=user, action=action, from_status=before,
        to_status=pay.status, note=(note or "").strip(), created_at=pay.updated_at,
    )


def _move(pay, status):
    pay.status = status
    pay.updated_at = timezone.now()
    pay.save(update_fields=["status", "updated_at"])
    Proposal.objects.filter(pk=pay.proposal_id).update(
        updated_at=pay.updated_at,
        **({"status": Proposal.Status.HOAN_THANH} if status == PS.HOAN_TAT else {}),
    )


def _check_amount(amount):
    if not amount or amount <= 0:
        raise WorkflowError("Cần ghi số tiền.")


def _fill(pay, user, amount, note, files, remove_ids):
    _check_amount(amount)
    if not user.bank_account_number:
        raise WorkflowError("Bạn chưa có tài khoản nhận tiền. Vào Tài khoản để cập nhật trước.")
    kept = pay.pk and pay.attachments.exclude(pk__in=remove_ids or []).exists()
    if pay.kind == K.THANH_TOAN and not files and not kept:
        raise WorkflowError("Thanh toán tự ứng phải kèm hóa đơn hoặc chứng từ.")
    pay.amount, pay.note = amount, (note or "").strip()
    pay.bank_name = user.bank_name
    pay.bank_account_number = user.bank_account_number
    pay.bank_account_holder = user.bank_account_holder
    pay.status = _FIRST_STEP[pay.kind]
    pay.updated_at = timezone.now()
    pay.save()
    attachments.remove(remove_ids, pay.proposal, pay)
    if files:
        attachments.save(files, user, pay.proposal, pay)
    Proposal.objects.filter(pk=pay.proposal_id).update(updated_at=pay.updated_at)


@transaction.atomic
def create(user, proposal, kind, amount, note="", files=()):
    proposal = Proposal.objects.get(pk=proposal.pk)
    if kind not in K.values:
        raise WorkflowError("Loại phiếu không hợp lệ.")
    if not can_request_money(user, proposal):
        raise WorkflowError("Đề xuất này không ở trạng thái xin tiền được, hoặc đã có phiếu đang chạy.")
    pay = PaymentRequest(code=next_code(PaymentRequest, _CODE_PREFIX[kind]), proposal=proposal, kind=kind,
                         requester=user)
    _fill(pay, user, amount, note, files, ())
    _log(pay, user, A.SUBMIT, "", note)
    return pay


@transaction.atomic
def resubmit(user, pay, amount, note="", files=(), remove_ids=()):
    pay = _reload(pay)
    if EDIT not in actions_for(user, pay):
        raise WorkflowError("Phiếu này không ở trạng thái sửa được.")
    before = pay.status
    _fill(pay, user, amount, note, files, remove_ids)
    _log(pay, user, A.RESUBMIT, before, note)
    return pay


@transaction.atomic
def approve(user, pay, note=""):
    pay = _reload(pay)
    if APPROVE not in actions_for(user, pay):
        raise WorkflowError("Phiếu này không còn chờ bạn duyệt.")
    before = pay.status
    _move(pay, _APPROVAL_STEPS[before][1])
    _log(pay, user, A.APPROVE, before, note)
    return pay


@transaction.atomic
def return_(user, pay, reason):
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("Phải có lý do trả về.")
    pay = _reload(pay)
    if RETURN not in actions_for(user, pay):
        raise WorkflowError("Phiếu này không còn chờ bạn duyệt.")
    before = pay.status
    _move(pay, _APPROVAL_STEPS[before][2])
    _log(pay, user, A.RETURN, before, reason)
    return pay


@transaction.atomic
def transfer(user, pay, note="", files=()):
    """Kế toán xác nhận đã chuyển tạm ứng cho thu mua (có thể kèm ủy nhiệm chi)."""
    pay = _reload(pay)
    if TRANSFER not in actions_for(user, pay):
        raise WorkflowError("Phiếu này không chờ bạn chuyển tiền.")
    before = pay.status
    if files:
        attachments.save(files, user, pay.proposal, pay)
    _move(pay, PS.DANG_MUA)
    _log(pay, user, A.TRANSFER, before, note)
    return pay


@transaction.atomic
def settle(user, pay, spent, note="", files=()):
    """Thu mua đã mua xong, đề nghị hoàn tạm ứng: ghi số thực chi, kèm hóa đơn nếu có."""
    pay = _reload(pay)
    if SETTLE not in actions_for(user, pay):
        raise WorkflowError("Phiếu này không ở bước đề nghị hoàn ứng.")
    if spent is None:
        raise WorkflowError("Cần ghi số tiền thực chi.")
    before = pay.status
    pay.spent = spent
    pay.save(update_fields=["spent"])
    if files:
        attachments.save(files, user, pay.proposal, pay)
    _move(pay, PS.CHO_DUYET_HOAN_UNG)
    _log(pay, user, A.SETTLE, before, note)
    return pay


@transaction.atomic
def cancel(user, pay, note=""):
    pay = _reload(pay)
    if CANCEL not in actions_for(user, pay):
        raise WorkflowError("Không thể hủy phiếu này.")
    before = pay.status
    _move(pay, PS.DA_HUY)
    _log(pay, user, A.CANCEL, before, note)
    return pay
