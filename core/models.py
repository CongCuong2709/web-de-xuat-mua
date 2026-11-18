from django.db import models


class AppSettings(models.Model):
    """Cấu hình chung, chỉ có một dòng (pk=1). Sửa trong trang quản trị."""

    chairman_threshold = models.PositiveBigIntegerField(
        "Mốc cần Chủ tịch duyệt (đồng)",
        default=10_000_000,
        help_text="Đề xuất có tổng tiền từ mốc này trở lên cần Chủ tịch duyệt thêm sau Giám đốc.",
    )

    class Meta:
        verbose_name = "Cấu hình chung"
        verbose_name_plural = "Cấu hình chung"

    def __str__(self):
        return "Cấu hình chung"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ReturnReason(models.Model):
    """Lý do trả về có sẵn để chọn nhanh. Người duyệt vẫn được gõ lý do khác."""

    text = models.CharField("Lý do", max_length=200)
    order = models.PositiveSmallIntegerField("Thứ tự", default=0)
    is_active = models.BooleanField("Đang dùng", default=True)

    class Meta:
        verbose_name = "Lý do trả về"
        verbose_name_plural = "Lý do trả về"
        ordering = ["order", "id"]

    def __str__(self):
        return self.text
