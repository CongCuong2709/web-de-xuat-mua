import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Proposal(models.Model):
    class Status(models.TextChoices):
        CHO_TRUONG_PHONG = "cho_truong_phong", "Chờ trưởng phòng"
        CHO_GIAM_DOC = "cho_giam_doc", "Chờ Giám đốc duyệt"
        CHO_CHU_TICH = "cho_chu_tich", "Chờ Chủ tịch duyệt"
        TRA_VE = "tra_ve", "Bị trả về"
        DA_DUYET = "da_duyet", "Đã duyệt · chờ mua"
        HOAN_THANH = "hoan_thanh", "Hoàn thành"
        DA_HUY = "da_huy", "Đã hủy"

    PENDING = (Status.CHO_TRUONG_PHONG, Status.CHO_GIAM_DOC, Status.CHO_CHU_TICH)

    code = models.CharField("Mã", max_length=20, unique=True, editable=False)
    title = models.CharField("Cần mua gì", max_length=200)
    reason = models.TextField("Lý do, mục đích")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Người đề xuất", on_delete=models.PROTECT, related_name="proposals"
    )
    # Chụp lại lúc gửi, để đổi tổ chức sau này không làm lệch đơn đang chạy.
    department = models.ForeignKey(
        "accounts.Department", verbose_name="Phòng ban", null=True, blank=True, on_delete=models.PROTECT
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Trưởng phòng duyệt",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, db_index=True)
    total = models.PositiveBigIntegerField("Tổng ước tính (đ)", default=0)
    needs_chairman = models.BooleanField("Cần Chủ tịch duyệt", default=False)
    created_at = models.DateTimeField("Ngày tạo", default=timezone.now)
    updated_at = models.DateTimeField("Cập nhật", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Đề xuất"
        verbose_name_plural = "Đề xuất"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.code} · {self.title}"

    @property
    def is_pending(self):
        return self.status in self.PENDING

    @property
    def active_payment(self):
        """Phiếu tạm ứng/thanh toán đang chạy (chưa hủy). Mỗi đề xuất chỉ một phiếu."""
        for pay in self.payments.all():  # dùng prefetch nếu có
            if pay.status != PaymentRequest.Status.DA_HUY:
                return pay
        return None

    @property
    def status_label(self):
        pay = self.active_payment if self.status == self.Status.DA_DUYET else None
        return pay.get_status_display() if pay else self.get_status_display()

    @property
    def pill_class(self):
        if self.is_pending:
            return "pill-wait"
        if self.status == self.Status.DA_DUYET:
            return "pill-money" if self.active_payment else "pill-done"
        return {
            self.Status.TRA_VE: "pill-back",
            self.Status.HOAN_THANH: "pill-done",
        }.get(self.status, "pill-muted")

    @property
    def waiting_on(self):
        """Đơn đang kẹt ở ai (cột Đang chờ)."""
        S = self.Status
        if self.status == S.DA_DUYET:
            pay = self.active_payment
            return pay.waiting_on if pay else "Thu mua"
        return {
            S.CHO_TRUONG_PHONG: str(self.manager) if self.manager_id else "Trưởng phòng",
            S.CHO_GIAM_DOC: "Giám đốc",
            S.CHO_CHU_TICH: "Chủ tịch",
            S.TRA_VE: f"{self.creator} (sửa đơn)",
        }.get(self.status, "—")

    @property
    def last_log(self):
        logs = list(self.logs.all())  # dùng prefetch nếu có
        return logs[-1] if logs else None


class ProposalItem(models.Model):
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="items")
    name = models.CharField("Tên món", max_length=200)
    quantity = models.DecimalField("Số lượng", max_digits=10, decimal_places=2, default=1)
    unit_price = models.PositiveBigIntegerField("Đơn giá ước tính (đ)", null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Món"
        verbose_name_plural = "Danh sách món"
        ordering = ["order", "id"]

    def __str__(self):
        return self.name

    @property
    def line_total(self):
        return round(self.quantity * self.unit_price) if self.unit_price is not None else None


class PaymentRequest(models.Model):
    """Phiếu tiền của một đề xuất đã duyệt. Người nhận tiền luôn là thu mua.

    Tạm ứng (TU):  Chủ tịch duyệt -> Kế toán chuyển tiền -> Thu mua mua hàng, đề nghị hoàn ứng
                   -> Chủ tịch duyệt hoàn ứng -> Hoàn tất
    Thanh toán (TT, thu mua đã tự ứng tiền, bắt buộc hóa đơn):
                   Kế toán duyệt -> Chủ tịch duyệt và hoàn tiền -> Hoàn tất
    """

    class Kind(models.TextChoices):
        TAM_UNG = "tam_ung", "Tạm ứng"
        THANH_TOAN = "thanh_toan", "Thanh toán tự ứng"

    class Status(models.TextChoices):
        CHO_CHU_TICH_UNG = "cho_ct_tam_ung", "Chờ Chủ tịch duyệt tạm ứng"
        CHO_CHUYEN_TIEN = "cho_chuyen_tien", "Chờ kế toán chuyển tiền"
        DANG_MUA = "dang_mua", "Đã nhận tạm ứng · đang mua"
        CHO_DUYET_HOAN_UNG = "cho_ct_hoan_ung", "Chờ Chủ tịch duyệt hoàn ứng"
        CHO_KE_TOAN = "cho_ke_toan", "Chờ kế toán duyệt chi"
        CHO_CHU_TICH_CHI = "cho_ct_chi", "Chờ Chủ tịch duyệt chi"
        TRA_VE = "tt_tra_ve", "Phiếu bị trả về"
        HOAN_TAT = "hoan_tat", "Đã hoàn tất"
        DA_HUY = "tt_da_huy", "Đã hủy phiếu"

    code = models.CharField("Mã", max_length=20, unique=True, editable=False)
    proposal = models.ForeignKey(Proposal, verbose_name="Đề xuất", on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField("Loại", max_length=20, choices=Kind.choices)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, db_index=True)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Thu mua", on_delete=models.PROTECT, related_name="payment_requests"
    )
    amount = models.PositiveBigIntegerField("Số tiền đề nghị (đ)")
    spent = models.PositiveBigIntegerField("Thực chi (đ)", null=True, blank=True, help_text="Tạm ứng: số tiền thực mua.")
    note = models.TextField("Ghi chú", blank=True)
    # Chụp lại tài khoản nhận tiền lúc gửi phiếu
    bank_name = models.CharField("Ngân hàng", max_length=100, blank=True)
    bank_account_number = models.CharField("Số tài khoản", max_length=30, blank=True)
    bank_account_holder = models.CharField("Chủ tài khoản", max_length=150, blank=True)
    created_at = models.DateTimeField("Ngày tạo", default=timezone.now)
    updated_at = models.DateTimeField("Cập nhật", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Phiếu tạm ứng / thanh toán"
        verbose_name_plural = "Phiếu tạm ứng / thanh toán"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.code} · {self.get_kind_display()}"

    @property
    def is_advance(self):
        return self.kind == self.Kind.TAM_UNG

    @property
    def title(self):
        return f"{'Tạm ứng' if self.is_advance else 'Thanh toán'}: {self.proposal.title}"

    @property
    def difference(self):
        """Tạm ứng đã quyết toán: dương = thu mua còn giữ thừa, âm = công ty còn thiếu thu mua."""
        if self.is_advance and self.spent is not None:
            return self.amount - self.spent
        return None

    @property
    def shortfall(self):
        d = self.difference
        return -d if d is not None and d < 0 else 0

    @property
    def pill_class(self):
        S = self.Status
        if self.status == S.TRA_VE:
            return "pill-back"
        if self.status == S.HOAN_TAT:
            return "pill-done"
        if self.status == S.DA_HUY:
            return "pill-muted"
        if self.status == S.DANG_MUA:
            return "pill-money"
        return "pill-wait"

    @property
    def waiting_on(self):
        S = self.Status
        return {
            S.CHO_CHU_TICH_UNG: "Chủ tịch",
            S.CHO_CHUYEN_TIEN: "Kế toán",
            S.DANG_MUA: f"{self.requester} (mua hàng)",
            S.CHO_DUYET_HOAN_UNG: "Chủ tịch",
            S.CHO_KE_TOAN: "Kế toán",
            S.CHO_CHU_TICH_CHI: "Chủ tịch",
            S.TRA_VE: f"{self.requester} (sửa phiếu)",
        }.get(self.status, "—")

    @property
    def last_log(self):
        logs = list(self.logs.all())
        return logs[-1] if logs else None


def _upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"attachments/{timezone.localtime():%Y/%m}/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    """Ảnh, hóa đơn, chứng từ. Luôn thuộc một đề xuất; ai xem được đề xuất thì xem được file.
    Không có URL công khai: file chỉ tải qua view có kiểm tra quyền."""

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="attachments")
    payment = models.ForeignKey(
        PaymentRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=_upload_to, max_length=200)
    name = models.CharField("Tên file", max_length=200)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "File đính kèm"
        verbose_name_plural = "File đính kèm"
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return self.name

    @property
    def is_image(self):
        return os.path.splitext(self.file.name)[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")


class ApprovalLog(models.Model):
    """Lịch sử: mỗi thao tác ghi một dòng, không sửa, không xóa.
    Dòng của phiếu tiền có cả proposal và payment, nên lịch sử đề xuất thấy luôn phần tiền."""

    class Action(models.TextChoices):
        SUBMIT = "submit", "Tạo"
        RESUBMIT = "resubmit", "Sửa và gửi lại"
        APPROVE = "approve", "Duyệt"
        RETURN = "return", "Trả về"
        CANCEL = "cancel", "Hủy"
        TRANSFER = "transfer", "Chuyển tiền"
        SETTLE = "settle", "Đề nghị hoàn ứng"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="logs")
    payment = models.ForeignKey(PaymentRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người thực hiện", on_delete=models.PROTECT)
    action = models.CharField("Thao tác", max_length=20, choices=Action.choices)
    from_status = models.CharField("Từ", max_length=20, blank=True)
    to_status = models.CharField("Sang", max_length=20)
    note = models.TextField("Ghi chú / lý do", blank=True)
    created_at = models.DateTimeField("Lúc", default=timezone.now)

    class Meta:
        verbose_name = "Lịch sử duyệt"
        verbose_name_plural = "Lịch sử duyệt"
        ordering = ["created_at", "id"]

    PS = PaymentRequest.Status
    STEP_NAMES = {
        Proposal.Status.CHO_TRUONG_PHONG: "Trưởng phòng",
        Proposal.Status.CHO_GIAM_DOC: "Giám đốc",
        Proposal.Status.CHO_CHU_TICH: "Chủ tịch",
        PS.CHO_CHU_TICH_UNG: "Chủ tịch",
        PS.CHO_DUYET_HOAN_UNG: "Chủ tịch",
        PS.CHO_CHU_TICH_CHI: "Chủ tịch",
        PS.CHO_KE_TOAN: "Kế toán",
        PS.CHO_CHUYEN_TIEN: "Kế toán",
    }

    @property
    def step_name(self):
        return self.STEP_NAMES.get(self.from_status, "")

    def _what(self):
        """Phiếu tiền thì nói rõ đang làm gì, ví dụ 'tạm ứng TU-202611-0001'."""
        p = self.payment
        if p is None:
            return ""
        S = PaymentRequest.Status
        if self.from_status == S.CHO_DUYET_HOAN_UNG:
            return f"hoàn ứng {p.code}"
        return f"{'tạm ứng' if p.is_advance else 'thanh toán'} {p.code}"

    @property
    def sentence(self):
        """Câu hiển thị trên tiến trình, ví dụ 'Giám đốc Lê Văn A duyệt'."""
        A = self.Action
        who = str(self.actor)
        what = self._what()
        if self.payment_id:
            if self.action == A.SUBMIT:
                return f"{who} gửi đề nghị {what}"
            if self.action == A.RESUBMIT:
                return f"{who} sửa và gửi lại {what}"
            if self.action == A.TRANSFER:
                return f"Kế toán {who} đã chuyển tiền {what}"
            if self.action == A.SETTLE:
                return f"{who} đề nghị hoàn ứng {self.payment.code}"
            if self.action == A.CANCEL:
                return f"{who} hủy phiếu {self.payment.code}"
            verb = "duyệt" if self.action == A.APPROVE else "trả về"
            return f"{self.step_name} {who} {verb} {what}".strip()
        if self.action == A.SUBMIT:
            return f"{who} tạo đề xuất"
        if self.action == A.RESUBMIT:
            return f"{who} sửa và gửi lại"
        if self.action == A.CANCEL:
            return f"{who} hủy đề xuất"
        verb = "duyệt" if self.action == A.APPROVE else "trả về"
        return f"{self.step_name} {who} {verb}".strip()

    @property
    def short(self):
        """Câu ngắn trên thẻ ở trang Chờ tôi xử lý."""
        A = self.Action
        if self.action == A.SUBMIT:
            return "Mới gửi"
        if self.action == A.RESUBMIT:
            return "Đã sửa, gửi lại"
        if self.action == A.APPROVE:
            return f"{self.step_name} đã duyệt"
        if self.action == A.RETURN:
            return f"{self.step_name} trả về"
        if self.action == A.TRANSFER:
            return "Kế toán đã chuyển tiền"
        if self.action == A.SETTLE:
            return "Đã mua, đề nghị hoàn ứng"
        return self.get_action_display()
