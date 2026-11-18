from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Người dùng. Vai trò, phòng ban, trưởng phòng trực tiếp thêm ở Chặng 1."""

    full_name = models.CharField("Họ tên", max_length=150, blank=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"

    def __str__(self):
        return self.full_name or self.username

    @property
    def display_name(self):
        return self.full_name or self.username
