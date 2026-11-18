from django.contrib import admin

from .models import ApprovalLog, Attachment, PaymentRequest, Proposal, ProposalItem


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ItemInline(ReadOnlyInline):
    model = ProposalItem
    fields = ("name", "quantity", "unit_price")


class LogInline(ReadOnlyInline):
    model = ApprovalLog
    fields = ("created_at", "actor", "action", "from_status", "to_status", "note")


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    """Chỉ xem: đề xuất chỉ thay đổi qua luồng duyệt để lịch sử luôn đúng."""

    list_display = ("code", "title", "creator", "department", "total", "status", "updated_at")
    list_filter = ("status", "department")
    search_fields = ("code", "title", "creator__full_name", "creator__username")
    inlines = [ItemInline, LogInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AttachmentInline(ReadOnlyInline):
    model = Attachment
    fields = ("name", "size", "uploaded_by", "uploaded_at")


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    """Chỉ xem, như đề xuất."""

    list_display = ("code", "kind", "proposal", "requester", "amount", "spent", "status", "updated_at")
    list_filter = ("kind", "status")
    search_fields = ("code", "proposal__code", "proposal__title")
    inlines = [AttachmentInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
