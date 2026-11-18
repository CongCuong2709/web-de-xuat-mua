from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Trang chủ = Chờ tôi xử lý. Chặng 2 sẽ đổ dữ liệu thật vào đây."""
    return render(request, "home.html", {"items": []})
