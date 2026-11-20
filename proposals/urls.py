from django.urls import path

from . import views, views_money, views_print

urlpatterns = [
    path("", views.home, name="home"),
    path("de-xuat/", views.proposal_list, name="proposal_list"),
    path("de-xuat/tao/", views.create, name="proposal_create"),
    path("de-xuat/<str:code>/", views.detail, name="proposal_detail"),
    path("de-xuat/<str:code>/sua/", views.edit, name="proposal_edit"),
    path("de-xuat/<str:code>/xu-ly/", views.act, name="proposal_act"),
    path("de-xuat/<str:code>/in/", views_print.print_proposal, name="proposal_print"),
    path("de-xuat/<str:code>/xin-tien/", views_money.payment_create, name="payment_create"),
    path("tien/", views_money.payment_list, name="payment_list"),
    path("tien/<str:code>/", views_money.payment_detail, name="payment_detail"),
    path("tien/<str:code>/sua/", views_money.payment_edit, name="payment_edit"),
    path("tien/<str:code>/hoan-ung/", views_money.payment_settle, name="payment_settle"),
    path("tien/<str:code>/xu-ly/", views_money.payment_act, name="payment_act"),
    path("tien/<str:code>/in/", views_print.print_payment, name="payment_print"),
    path("tep/<int:pk>/", views.attachment, name="attachment"),
]
