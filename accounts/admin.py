from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "is_active", "is_staff", "last_login")
    search_fields = ("username", "full_name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Thông tin", {"fields": ("full_name", "email")}),
        ("Quyền", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Mốc thời gian", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "full_name", "password1", "password2")}),)
