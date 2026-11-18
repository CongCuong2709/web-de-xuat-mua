from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views

admin.site.site_header = "Quản trị · Đề xuất mua sắm"
admin.site.site_title = "Quản trị"

urlpatterns = [
    path("", views.home, name="home"),
    path("dang-nhap/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
    path("quan-tri/", admin.site.urls),
]
