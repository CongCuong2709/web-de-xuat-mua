from django.db import migrations

ROLES = [
    ("nhan_vien", "Nhân viên"),
    ("truong_phong", "Trưởng phòng"),
    ("giam_doc", "Giám đốc"),
    ("chu_tich", "Chủ tịch"),
    ("ke_toan", "Kế toán"),
    ("thu_mua", "Thu mua"),
]


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for i, (code, name) in enumerate(ROLES):
        Role.objects.update_or_create(code=code, defaults={"name": name, "order": i})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
