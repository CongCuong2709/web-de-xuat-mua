# Đề xuất mua sắm

Web app số hóa quy trình đề xuất và phê duyệt mua sắm nội bộ.
Django 5.2 · SQLite · HTMX/Alpine · chạy ở `localhost:8100`, ra ngoài qua Cloudflare Tunnel.

## Cài lần đầu (Windows, Python 3.10+)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Chạy

| Lệnh | Dùng khi |
|---|---|
| `.\dev.ps1` | Đang phát triển: tự nạp lại khi sửa code, báo lỗi chi tiết |
| `.\run.ps1` | Dùng thật trên máy công ty (waitress) |
| `.\.venv\Scripts\python.exe -m pytest` | Chạy test |

Trang quản trị: `/quan-tri/`.

Dữ liệu mẫu để thử (9 tài khoản: chủ tịch, 2 giám đốc, kế toán, thu mua, 2 trưởng phòng, 2 nhân viên; mật khẩu `123456`):

```powershell
$env:DEBUG="1"; .\.venv\Scripts\python.exe manage.py tao_du_lieu_mau
```

## Quản lý tài khoản (quản trị viên)

- **Tạo tài khoản**: Quản trị → Người dùng → Thêm. Chọn phòng ban, vai trò (được chọn nhiều), trưởng phòng trực tiếp. Người mới phải đổi mật khẩu ở lần đăng nhập đầu.
- **Quên mật khẩu**: tick người dùng → hành động *Đặt lại mật khẩu* → báo mật khẩu tạm cho họ. Họ sẽ phải đổi khi đăng nhập.
- **Quản trị viên** = tick *Trạng thái superuser*.
- **Mốc Chủ tịch duyệt** và **Lý do trả về**: mục *Cấu hình*.

## Cấu hình theo máy

Tạo file `.env` ở thư mục gốc (không đưa lên git):

```
HOSTS=localhost,127.0.0.1,ten-mien-cloudflare.vn
```

`HOSTS` phải có tên miền Cloudflare Tunnel thì truy cập từ ngoài mới được.

## Dữ liệu

Mọi dữ liệu nằm trong thư mục `data/`: `db.sqlite3`, `media/` (chứng từ), `secret_key.txt`.
Sao lưu = chép cả thư mục `data/`.

## Cấu trúc

```
config/      cấu hình Django, urls
accounts/    người dùng, phòng ban, vai trò, đăng nhập, đổi mật khẩu
core/        cấu hình chung (mốc tiền), lý do trả về
templates/   giao diện
static/      CSS, htmx, alpine (không cần Node)
tests/       pytest
```
