"""Tạo tài khoản mẫu để thử trên máy phát triển. Mật khẩu chung: 123456.

    .\\.venv\\Scripts\\python.exe manage.py tao_du_lieu_mau
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Department, Role, User

PASSWORD = "123456"

# username, họ tên, phòng ban, vai trò, trưởng phòng
USERS = [
    ("chutich", "Trần Chủ Tịch", "Ban lãnh đạo", [Role.CHU_TICH], None),
    ("giamdoc1", "Lê Giám Đốc", "Ban lãnh đạo", [Role.GIAM_DOC], None),
    ("giamdoc2", "Phạm Giám Đốc", "Ban lãnh đạo", [Role.GIAM_DOC], None),
    ("ketoan", "Đỗ Kế Toán", "Kế toán", [Role.KE_TOAN], None),
    ("thumua", "Vũ Thu Mua", "Thu mua", [Role.THU_MUA], None),
    ("tp_kythuat", "Hoàng Trưởng Kỹ Thuật", "Kỹ thuật", [Role.TRUONG_PHONG], None),
    ("tp_kinhdoanh", "Bùi Trưởng Kinh Doanh", "Kinh doanh", [Role.TRUONG_PHONG], None),
    ("nv_kythuat", "Nguyễn Văn An", "Kỹ thuật", [Role.NHAN_VIEN], "tp_kythuat"),
    ("nv_kinhdoanh", "Ngô Thị Bình", "Kinh doanh", [Role.NHAN_VIEN], "tp_kinhdoanh"),
]


class Command(BaseCommand):
    help = "Tạo phòng ban và tài khoản mẫu (chỉ dùng khi phát triển)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Chạy cả khi DEBUG tắt")

    def handle(self, *args, force=False, **opts):
        if not settings.DEBUG and not force:
            raise CommandError("Đây là dữ liệu mẫu. Chỉ chạy khi DEBUG=1, hoặc thêm --force.")
        roles = {r.code: r for r in Role.objects.all()}
        created = 0
        for username, name, dept, codes, manager in USERS:
            if User.objects.filter(username=username).exists():
                continue
            u = User.objects.create_user(
                username,
                password=PASSWORD,
                full_name=name,
                department=Department.objects.get_or_create(name=dept)[0],
                manager=User.objects.get(username=manager) if manager else None,
            )
            u.roles.set([roles[c] for c in codes])
            if Role.THU_MUA in codes:
                u.bank_name, u.bank_account_number, u.bank_account_holder = "Vietcombank", "0123456789", name.upper()
                u.save()
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Đã tạo {created} tài khoản mẫu, mật khẩu: {PASSWORD}"))
