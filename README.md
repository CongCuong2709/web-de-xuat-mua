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

## Luồng đề xuất (Chặng 2)

Nhân viên tạo → Trưởng phòng trực tiếp → Giám đốc (1 trong 2) → Chủ tịch (nếu tổng ≥ mốc) → Đã duyệt, chờ thu mua.
Bước nào cũng trả về được (bắt buộc lý do), đơn về người tạo sửa và gửi lại từ đầu, không giới hạn số lần.
Người tạo được hủy khi đơn bị trả về hoặc trưởng phòng chưa xử lý.
Luật nằm trong `proposals/workflow.py`; đổi luật thì sửa ở đó và test trong `tests/test_workflow.py`.

## Luồng tiền (Chặng 3)

Đề xuất đã duyệt → thu mua chọn một trong hai:

- **Xin tạm ứng (TU)**: Chủ tịch duyệt → Kế toán chuyển tiền → thu mua mua hàng, đề nghị hoàn ứng (ghi số thực chi, kèm hóa đơn nếu có) → Chủ tịch duyệt hoàn ứng.
- **Đã tự ứng, đề nghị thanh toán (TT)**: bắt buộc kèm hóa đơn → Kế toán duyệt chi → Chủ tịch duyệt và hoàn tiền.

Tiền luôn về tài khoản của thu mua (thu mua tự cập nhật ở trang Tài khoản). Mỗi đề xuất một phiếu đang chạy; hủy phiếu thì lập phiếu mới.
Phiếu hoàn tất → đề xuất chuyển sang Hoàn thành. Thừa/thiếu khi hoàn ứng chỉ hiển thị, chưa có luồng xử lý riêng.
Luật nằm trong `proposals/payments.py`, test trong `tests/test_payments.py`.

File đính kèm (ảnh, PDF, Word, Excel; tối đa 15 MB/file, ảnh lớn tự thu nhỏ) lưu trong `data/media/`,
chỉ tải được qua `/tep/<id>/` khi người xem có quyền xem đề xuất đó.

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
proposals/   đề xuất, phiếu tiền, file, lịch sử; workflow.py = luật duyệt, payments.py = luật tiền
templates/   giao diện
static/      CSS, htmx, alpine (không cần Node)
tests/       pytest
```
