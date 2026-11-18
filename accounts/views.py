from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


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
