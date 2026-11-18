from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Department(models.Model):
    name = models.CharField("Tên phòng ban", max_length=100, unique=True)

    class Meta:
        verbose_name = "Phòng ban"
        verbose_name_plural = "Phòng ban"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.Model):
    """Vai trò cố định, tạo sẵn bằng migration. Một người có thể có nhiều vai trò."""

    NHAN_VIEN = "nhan_vien"
    TRUONG_PHONG = "truong_phong"
    GIAM_DOC = "giam_doc"
    CHU_TICH = "chu_tich"
    KE_TOAN = "ke_toan"
    THU_MUA = "thu_mua"
    CHOICES = [
        (NHAN_VIEN, "Nhân viên (tạo đề xuất)"),
        (TRUONG_PHONG, "Trưởng phòng"),
        (GIAM_DOC, "Giám đốc"),
        (CHU_TICH, "Chủ tịch"),
        (KE_TOAN, "Kế toán"),
        (THU_MUA, "Thu mua"),
    ]

    code = models.CharField(max_length=20, unique=True, choices=CHOICES)
    name = models.CharField("Tên vai trò", max_length=50)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Vai trò"
        verbose_name_plural = "Vai trò"
        ordering = ["order"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    full_name = models.CharField("Họ tên", max_length=150, blank=True)
    department = models.ForeignKey(
        Department, verbose_name="Phòng ban", null=True, blank=True, on_delete=models.PROTECT, related_name="members"
    )
    roles = models.ManyToManyField(Role, verbose_name="Vai trò", blank=True, related_name="users")
    manager = models.ForeignKey(
        "self",
        verbose_name="Trưởng phòng trực tiếp",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reports",
        help_text="Người duyệt bước đầu tiên cho đề xuất của người này.",
    )
    must_change_password = models.BooleanField(
        "Phải đổi mật khẩu", default=False, help_text="Bật khi quản trị viên tạo tài khoản hoặc đặt lại mật khẩu."
    )
    # Tài khoản nhận tiền (thu mua nhận tạm ứng / hoàn tiền)
    bank_name = models.CharField("Ngân hàng", max_length=100, blank=True)
    bank_account_number = models.CharField("Số tài khoản", max_length=30, blank=True)
    bank_account_holder = models.CharField("Chủ tài khoản", max_length=150, blank=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"
        ordering = ["full_name", "username"]

    def __str__(self):
        return self.full_name or self.username

    @property
    def display_name(self):
        return self.full_name or self.username

    def role_codes(self):
        if not hasattr(self, "_role_codes"):
            self._role_codes = set(self.roles.values_list("code", flat=True)) if self.pk else set()
        return self._role_codes

    def has_role(self, *codes):
        return bool(self.role_codes() & set(codes))

    def clean(self):
        super().clean()
        if self.manager_id and self.manager_id == self.pk:
            raise ValidationError({"manager": "Không thể tự làm trưởng phòng trực tiếp của mình."})
