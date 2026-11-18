from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("de-xuat/", views.proposal_list, name="proposal_list"),
    path("de-xuat/tao/", views.create, name="proposal_create"),
    path("de-xuat/<str:code>/", views.detail, name="proposal_detail"),
    path("de-xuat/<str:code>/sua/", views.edit, name="proposal_edit"),
    path("de-xuat/<str:code>/xu-ly/", views.act, name="proposal_act"),
]
