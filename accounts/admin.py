import secrets

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm, AdminUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth.models import Group

from .models import Department, Role, User

admin.site.unregister(Group)  # dùng Vai trò thay cho Group của Django


class _RoleRules:
    """Kiểm tra chung cho form tạo và sửa người dùng."""

    def clean(self):
        data = super().clean()
        roles = {r.code for r in data.get("roles") or []}
        manager = data.get("manager")
        if manager and not manager.has_role(Role.TRUONG_PHONG):
            self.add_error("manager", "Người này chưa có vai trò Trưởng phòng.")
        if Role.NHAN_VIEN in roles and not manager:
            self.add_error("manager", "Nhân viên tạo đề xuất cần có trưởng phòng trực tiếp.")
        return data


class UserChangeForm(_RoleRules, BaseUserChangeForm):
    class Meta(BaseUserChangeForm.Meta):
        model = User


class UserAddForm(_RoleRules, AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("username", "full_name", "department", "roles", "manager")


class ResetPasswordForm(AdminPasswordChangeForm):
    """Quản trị viên đặt lại mật khẩu: người dùng phải đổi ở lần đăng nhập kế tiếp."""

    def save(self, commit=True):
        self.user.must_change_password = True
        return super().save(commit)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserAddForm
    change_password_form = ResetPasswordForm
    list_display = ("username", "full_name", "department", "role_list", "manager", "is_active")
    list_filter = ("is_active", "department", "roles")
    search_fields = ("username", "full_name")
    ordering = ("full_name", "username")
    filter_horizontal = ()
    actions = ["reset_password"]
    fieldsets = (
        (None, {"fields": ("username", "password", "must_change_password")}),
        ("Thông tin", {"fields": ("full_name", "email", "department")}),
        ("Vai trò và duyệt", {"fields": ("roles", "manager")}),
        ("Tài khoản nhận tiền", {"fields": ("bank_name", "bank_account_number", "bank_account_holder")}),
        ("Quyền hệ thống", {"fields": ("is_active", "is_superuser")}),
        ("Mốc thời gian", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "full_name", "password1", "password2")}),
        ("Tổ chức", {"classes": ("wide",), "fields": ("department", "roles", "manager")}),
    )
    readonly_fields = ("last_login", "date_joined")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("department", "manager").prefetch_related("roles")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "manager":
            kwargs["queryset"] = User.objects.filter(roles__code=Role.TRUONG_PHONG, is_active=True).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "roles":
            kwargs["widget"] = forms.CheckboxSelectMultiple
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    @admin.display(description="Vai trò")
    def role_list(self, obj):
        return ", ".join(r.name for r in obj.roles.all())

    def save_model(self, request, obj, form, change):
        # Quản trị viên = superuser; giữ is_staff khớp để vào được trang quản trị.
        obj.is_staff = obj.is_superuser
        if not change:
            obj.must_change_password = True
        super().save_model(request, obj, form, change)

    @admin.action(description="Đặt lại mật khẩu (tạo mật khẩu tạm)")
    def reset_password(self, request, queryset):
        lines = []
        for user in queryset:
            temp = secrets.token_hex(3)  # 6 ký tự, dễ đọc qua điện thoại
            user.set_password(temp)
            user.must_change_password = True
            user.save(update_fields=["password", "must_change_password"])
            lines.append(f"{user.username}: {temp}")
        self.message_user(
            request,
            "Mật khẩu tạm (người dùng sẽ phải đổi khi đăng nhập): " + " · ".join(lines),
            messages.WARNING,
        )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "member_count")
    search_fields = ("name",)

    @admin.display(description="Số người")
    def member_count(self, obj):
        return obj.members.count()


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    """Chỉ xem: vai trò gắn với luật duyệt trong code, không thêm/xóa tay."""

    list_display = ("name", "code")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
