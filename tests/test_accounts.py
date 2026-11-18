import pytest
from django.urls import reverse

from accounts.admin import UserAddForm, UserChangeForm
from accounts.models import Department, Role, User
from core.models import AppSettings, ReturnReason

pytestmark = pytest.mark.django_db


def role(code):
    return Role.objects.get(code=code)


@pytest.fixture
def dept():
    return Department.objects.create(name="Kỹ thuật")


@pytest.fixture
def boss(dept):
    u = User.objects.create_user("tp", password="matkhau123", full_name="Trưởng Phòng", department=dept)
    u.roles.add(role(Role.TRUONG_PHONG))
    return u


@pytest.fixture
def admin_client(client):
    User.objects.create_superuser("admin", password="matkhau123")
    client.login(username="admin", password="matkhau123")
    return client


def test_roles_and_defaults_seeded():
    assert set(Role.objects.values_list("code", flat=True)) == {c for c, _ in Role.CHOICES}
    assert AppSettings.load().chairman_threshold == 10_000_000
    assert ReturnReason.objects.filter(is_active=True).count() == 4


def test_user_with_multiple_roles(boss):
    boss.roles.add(role(Role.KE_TOAN))
    boss = User.objects.get(pk=boss.pk)
    assert boss.has_role(Role.KE_TOAN)
    assert boss.has_role(Role.TRUONG_PHONG)
    assert not boss.has_role(Role.CHU_TICH)


def test_admin_creates_user_forced_to_change_password(admin_client, dept, boss):
    r = admin_client.post(
        reverse("admin:accounts_user_add"),
        {
            "username": "an",
            "full_name": "Nguyễn An",
            "password1": "tam12345",
            "password2": "tam12345",
            "usable_password": "true",
            "department": dept.pk,
            "roles": [role(Role.NHAN_VIEN).pk],
            "manager": boss.pk,
        },
    )
    assert r.status_code == 302, r.content.decode()[:2000]
    an = User.objects.get(username="an")
    assert an.must_change_password
    assert an.manager == boss
    assert an.has_role(Role.NHAN_VIEN)
    assert not an.is_staff


def test_staff_requires_manager(dept):
    form = UserAddForm(
        data={
            "username": "binh",
            "password1": "tam12345",
            "password2": "tam12345",
            "usable_password": "true",
            "department": dept.pk,
            "roles": [role(Role.NHAN_VIEN).pk],
        }
    )
    assert not form.is_valid()
    assert "manager" in form.errors


def test_manager_must_be_truong_phong(dept):
    not_boss = User.objects.create_user("x", password="matkhau123")
    u = User.objects.create_user("y", password="matkhau123")
    form = UserChangeForm(
        instance=u,
        data={"username": "y", "manager": not_boss.pk, "roles": [], "date_joined": "2026-01-01 00:00"},
    )
    assert not form.is_valid()
    assert "manager" in form.errors


def test_forced_password_change_flow(client):
    u = User.objects.create_user("an", password="tam12345", must_change_password=True)
    client.login(username="an", password="tam12345")
    # Mọi trang đều bị đẩy về đổi mật khẩu
    r = client.get(reverse("home"))
    assert r.status_code == 302 and r["Location"] == reverse("password_change")
    r = client.post(
        reverse("password_change"),
        {"old_password": "tam12345", "new_password1": "moi-cua-an-1", "new_password2": "moi-cua-an-1"},
    )
    assert r.status_code == 302 and r["Location"] == reverse("home")
    u.refresh_from_db()
    assert not u.must_change_password
    assert u.check_password("moi-cua-an-1")
    assert client.get(reverse("home")).status_code == 200  # vẫn đăng nhập


def test_admin_reset_password_action(admin_client):
    u = User.objects.create_user("an", password="matkhau123")
    r = admin_client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "reset_password", "_selected_action": [u.pk]},
        follow=True,
    )
    u.refresh_from_db()
    assert u.must_change_password
    assert not u.check_password("matkhau123")
    assert "an:" in r.content.decode()


def test_admin_set_password_form_forces_change(admin_client):
    u = User.objects.create_user("an", password="matkhau123")
    admin_client.post(
        reverse("admin:auth_user_password_change", args=[u.pk]),  # Django đặt tên cố định
        {"password1": "tam99999", "password2": "tam99999", "usable_password": "true"},
    )
    u.refresh_from_db()
    assert u.check_password("tam99999")
    assert u.must_change_password


def test_profile_page(client, boss):
    client.login(username="tp", password="matkhau123")
    body = client.get(reverse("profile")).content.decode()
    assert "Trưởng phòng" in body and "Kỹ thuật" in body


def test_admin_pages_render(admin_client):
    for name in ["admin:accounts_user_add", "admin:accounts_user_changelist", "admin:core_returnreason_changelist"]:
        assert admin_client.get(reverse(name)).status_code == 200
    u = User.objects.get(username="admin")
    html = admin_client.get(reverse("admin:accounts_user_change", args=[u.pk])).content.decode()
    assert 'type="checkbox" name="roles"' in html
    assert 'name="password"' not in html  # mật khẩu không hiện thành ô nhập thô
    assert admin_client.get(reverse("admin:auth_user_password_change", args=[u.pk])).status_code == 200
    r = admin_client.get(reverse("admin:core_appsettings_changelist"))
    assert r.status_code == 302
    assert admin_client.get(r["Location"]).status_code == 200
