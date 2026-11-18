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
    def pill_class(self):
        if self.is_pending:
            return "pill-wait"
        return {
            self.Status.TRA_VE: "pill-back",
            self.Status.DA_DUYET: "pill-done",
        }.get(self.status, "pill-muted")

    @property
    def waiting_on(self):
        """Đơn đang kẹt ở ai (cột Đang chờ)."""
        S = self.Status
        return {
            S.CHO_TRUONG_PHONG: str(self.manager) if self.manager_id else "Trưởng phòng",
            S.CHO_GIAM_DOC: "Giám đốc",
            S.CHO_CHU_TICH: "Chủ tịch",
            S.TRA_VE: f"{self.creator} (sửa đơn)",
            S.DA_DUYET: "Thu mua",
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


class ApprovalLog(models.Model):
    """Lịch sử: mỗi thao tác trên đề xuất ghi một dòng, không sửa, không xóa."""

    class Action(models.TextChoices):
        SUBMIT = "submit", "Tạo đề xuất"
        RESUBMIT = "resubmit", "Sửa và gửi lại"
        APPROVE = "approve", "Duyệt"
        RETURN = "return", "Trả về"
        CANCEL = "cancel", "Hủy"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="logs")
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

    STEP_NAMES = {
        Proposal.Status.CHO_TRUONG_PHONG: "Trưởng phòng",
        Proposal.Status.CHO_GIAM_DOC: "Giám đốc",
        Proposal.Status.CHO_CHU_TICH: "Chủ tịch",
    }

    @property
    def step_name(self):
        return self.STEP_NAMES.get(self.from_status, "")

    @property
    def sentence(self):
        """Câu hiển thị trên tiến trình, ví dụ 'Giám đốc Lê Văn A duyệt'."""
        A = self.Action
        who = str(self.actor)
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
        return self.get_action_display()
