import pytest

from accounts.models import Department, Role, User


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    settings.STORAGES = {**settings.STORAGES, "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # test nhanh
    settings.MEDIA_ROOT = tmp_path / "media"  # file test không lẫn vào data/


def make_user(username, *roles, manager=None, department=None):
    u = User.objects.create_user(username, password="matkhau123", full_name=username.upper(),
                                 manager=manager, department=department)
    u.roles.set(Role.objects.filter(code__in=roles))
    return User.objects.get(pk=u.pk)  # bỏ cache vai trò


@pytest.fixture
def org(db):
    """Tổ chức mẫu: 2 phòng, mỗi phòng 1 trưởng phòng + 1 nhân viên; 2 giám đốc, 1 chủ tịch, kế toán, thu mua."""
    kt = Department.objects.create(name="Kỹ thuật")
    kd = Department.objects.create(name="Kinh doanh")
    tp_kt = make_user("tp_kt", Role.TRUONG_PHONG, department=kt)
    tp_kd = make_user("tp_kd", Role.TRUONG_PHONG, department=kd)

    class O:
        pass

    o = O()
    o.kt, o.kd, o.tp_kt, o.tp_kd = kt, kd, tp_kt, tp_kd
    o.nv_kt = make_user("nv_kt", Role.NHAN_VIEN, manager=tp_kt, department=kt)
    o.nv_kd = make_user("nv_kd", Role.NHAN_VIEN, manager=tp_kd, department=kd)
    o.gd1 = make_user("gd1", Role.GIAM_DOC)
    o.gd2 = make_user("gd2", Role.GIAM_DOC)
    o.ct = make_user("ct", Role.CHU_TICH)
    o.ketoan = make_user("ketoan", Role.KE_TOAN)
    o.thumua = make_user("thumua", Role.THU_MUA)
    o.thumua.bank_name, o.thumua.bank_account_number, o.thumua.bank_account_holder = "VCB", "0123", "VU THU MUA"
    o.thumua.save()
    return o
