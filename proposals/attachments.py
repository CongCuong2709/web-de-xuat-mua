"""Nhận file tải lên: kiểm tra loại và dung lượng, thu nhỏ ảnh chụp điện thoại, lưu Attachment.

File nằm trong MEDIA_ROOT (data/media), không có URL công khai; chỉ tải qua view `attachment`
có kiểm tra quyền xem đề xuất.
"""
import io
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from .models import Attachment

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
INLINE = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}  # mở thẳng trên trình duyệt
MAX_SIZE = 15 * 1024 * 1024
MAX_FILES = 10
MAX_SIDE = 2000  # ảnh lớn hơn thì thu nhỏ, đỡ nặng khi xem qua điện thoại
ACCEPT = "image/*," + ",".join(sorted(ALLOWED))


def validate(files):
    """Trả về danh sách lỗi (rỗng nếu hợp lệ)."""
    errors = []
    if len(files) > MAX_FILES:
        errors.append(f"Tối đa {MAX_FILES} file mỗi lần gửi.")
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED:
            errors.append(f"{f.name}: không nhận loại file này (chỉ ảnh, PDF, Word, Excel).")
        elif f.size > MAX_SIZE:
            errors.append(f"{f.name}: lớn hơn {MAX_SIZE // 1024 // 1024} MB.")
    return errors


def _shrink(f):
    """Thu nhỏ ảnh JPEG/PNG/WEBP nếu cạnh dài > MAX_SIDE. Lỗi đọc ảnh thì giữ nguyên file gốc."""
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return f
    try:
        f.seek(0)
        img = Image.open(f)
        img = ImageOps.exif_transpose(img)  # ảnh điện thoại hay bị xoay
        if max(img.size) <= MAX_SIDE:
            f.seek(0)
            return f
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        if ext in (".jpg", ".jpeg"):
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        else:
            img.save(out, "PNG" if ext == ".png" else "WEBP", optimize=True)
        return ContentFile(out.getvalue(), name=f.name)
    except Exception:
        f.seek(0)
        return f


def save(files, user, proposal, payment=None):
    saved = []
    for f in files:
        data = _shrink(f)
        att = Attachment(proposal=proposal, payment=payment, name=os.path.basename(f.name)[:200], uploaded_by=user)
        att.file.save(f.name, data, save=False)
        att.size = att.file.size
        att.save()
        saved.append(att)
    return saved


def remove(ids, proposal, payment=None):
    """Xóa file theo id, chỉ trong phạm vi đề xuất/phiếu đang sửa."""
    if not ids:
        return
    qs = Attachment.objects.filter(pk__in=ids, proposal=proposal, payment=payment)
    for att in qs:
        att.file.delete(save=False)
        att.delete()
