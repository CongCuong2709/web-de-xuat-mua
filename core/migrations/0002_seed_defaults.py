from django.db import migrations

REASONS = [
    "Giá cao, cần xem lại giá",
    "Chưa cần thiết lúc này",
    "Thiếu thông tin món hàng",
    "Nên gộp với đơn khác",
]


def seed(apps, schema_editor):
    AppSettings = apps.get_model("core", "AppSettings")
    ReturnReason = apps.get_model("core", "ReturnReason")
    AppSettings.objects.get_or_create(pk=1)
    if not ReturnReason.objects.exists():
        for i, text in enumerate(REASONS):
            ReturnReason.objects.create(text=text, order=i)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
