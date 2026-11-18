import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse


def test_custom_user_model():
    assert settings.AUTH_USER_MODEL == "accounts.User"


@pytest.mark.django_db
def test_login_page_loads(client):
    r = client.get(reverse("login"))
    assert r.status_code == 200
    assert "Đăng nhập" in r.content.decode()


@pytest.mark.django_db
def test_home_requires_login(client):
    r = client.get(reverse("home"))
    assert r.status_code == 302
    assert reverse("login") in r["Location"]


@pytest.mark.django_db
def test_login_then_home(client):
    get_user_model().objects.create_user("an", password="matkhau123", full_name="Nguyễn Văn An")
    r = client.post(reverse("login"), {"username": "an", "password": "matkhau123"}, follow=True)
    assert r.status_code == 200
    body = r.content.decode()
    assert "Chờ tôi xử lý" in body
    assert "Nguyễn Văn An" in body
