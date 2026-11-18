from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Role


@login_required
def profile(request):
    """Xem thông tin; tự sửa tài khoản nhận tiền (thu mua nhận tạm ứng / hoàn tiền)."""
    user = request.user
    if request.method == "POST":
        user.bank_name = request.POST.get("bank_name", "").strip()[:100]
        user.bank_account_number = request.POST.get("bank_account_number", "").strip()[:30]
        user.bank_account_holder = request.POST.get("bank_account_holder", "").strip()[:150]
        user.save(update_fields=["bank_name", "bank_account_number", "bank_account_holder"])
        messages.success(request, "Đã lưu tài khoản nhận tiền.")
        nxt = request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect("profile")
    show_bank = user.has_role(Role.THU_MUA) or bool(user.bank_account_number)
    return render(request, "accounts/profile.html", {"next": request.GET.get("next", ""), "show_bank": show_bank})


@login_required
def password_change(request):
    forced = request.user.must_change_password
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.must_change_password = False
        user.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Đã đổi mật khẩu.")
        return redirect("home")
    return render(request, "accounts/password_change.html", {"form": form, "forced": forced})
