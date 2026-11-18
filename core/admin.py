from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import AppSettings, ReturnReason


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Chỉ có một dòng: bấm vào là sửa luôn.
        obj = AppSettings.load()
        return redirect(reverse("admin:core_appsettings_change", args=[obj.pk]))


@admin.register(ReturnReason)
class ReturnReasonAdmin(admin.ModelAdmin):
    list_display = ("text", "order", "is_active")
    list_editable = ("order", "is_active")
