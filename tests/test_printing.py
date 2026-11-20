from datetime import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from core.models import AppSettings
from proposals import payments as pm
from proposals import workflow as wf
from proposals.models import PaymentRequest
from proposals.printing import ngay_thang, proposal_signatures, so_thanh_chu


@pytest.mark.parametrize("n, words", [
    (0, "Không đồng"),
    (15, "Mười lăm đồng"),
    (21, "Hai mươi mốt đồng"),
    (105, "Một trăm linh năm đồng"),
    (1_005, "Một nghìn không trăm linh năm đồng"),
    (1_675_000, "Một triệu sáu trăm bảy mươi lăm nghìn đồng"),
    (18_500_000, "Mười tám triệu năm trăm nghìn đồng"),
    (1_000_005_000, "Một tỷ không trăm linh năm nghìn đồng"),
    (2_015_000_000, "Hai tỷ không trăm mười lăm triệu đồng"),
])
def test_so_thanh_chu(n, words):
    assert so_thanh_chu(n) == words


def test_ngay_thang_nd30():
    # Ngày < 10 và tháng 1, 2 thêm số 0; tháng 3-12 không thêm
    assert ngay_thang(datetime(2026, 1, 5)) == "ngày 05 tháng 01 năm 2026"
    assert ngay_thang(datetime(2026, 3, 5)) == "ngày 05 tháng 3 năm 2026"
    assert ngay_thang(datetime(2026, 11, 20)) == "ngày 20 tháng 11 năm 2026"


def _approved(org, total=12_000_000):
    p = wf.create(org.nv_kt, "Laptop HP", "Máy hỏng", [{"name": "Laptop", "quantity": Decimal(1), "unit_price": total}])
    p = wf.approve(org.tp_kt, p)
    p = wf.approve(org.gd2, p, "Đồng ý")
    return wf.approve(org.ct, p)


def test_signatures_follow_latest_submission(org):
    p = wf.create(org.nv_kt, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}])
    p = wf.approve(org.tp_kt, p)
    p = wf.return_(org.gd1, p, "Thiếu")
    p = wf.resubmit(org.nv_kt, p, "Ghế", "Rõ hơn", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}])
    sigs, _ = proposal_signatures(p)
    # Lượt duyệt của trưởng phòng trước khi trả về không được tính cho lượt gửi lại
    assert [s["title"] for s in sigs] == ["Người đề xuất", "Trưởng phòng", "Giám đốc"]
    assert sigs[1]["at"] is None and sigs[2]["user"] is None


def test_print_proposal(client, org):
    cfg = AppSettings.load()
    cfg.org_name, cfg.place_name = "CÔNG TY TNHH MẪU", "Hà Nội"
    cfg.save()
    p = _approved(org)
    client.force_login(org.ketoan)
    body = client.get(reverse("proposal_print", args=[p.code])).content.decode()
    assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in body and "Độc lập - Tự do - Hạnh phúc" in body
    assert "CÔNG TY TNHH MẪU" in body and f"Số: {p.code}" in body and "Hà Nội, ngày" in body
    assert "Về việc mua sắm laptop HP" in body
    assert "Mười hai triệu đồng" in body
    assert "GD2" in body and "“Đồng ý”" in body  # giám đốc đã duyệt, kèm ý kiến
    assert "Chủ tịch" in body and "Nơi nhận:" in body
    assert "Phòng Kỹ thuật kính trình" in body and "(Đã gửi trên hệ thống" in body
    assert "Chưa khai báo tên công ty" not in body


def test_print_warns_when_org_missing_and_not_final(client, org):
    p = wf.create(org.nv_kt, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}])
    client.force_login(org.nv_kt)
    body = client.get(reverse("proposal_print", args=[p.code])).content.decode()
    assert "Chưa khai báo tên công ty" in body and "chưa được duyệt xong" in body


def test_print_is_permission_checked(client, org):
    p = _approved(org)
    client.force_login(org.nv_kd)
    assert client.get(reverse("proposal_print", args=[p.code])).status_code == 404


def test_print_advance_and_settlement(client, org):
    p = _approved(org)
    pay = pm.create(org.thumua, p, PaymentRequest.Kind.TAM_UNG, 12_000_000)
    pay = pm.transfer(org.ketoan, pm.approve(org.ct, pay))
    client.force_login(org.thumua)
    body = client.get(reverse("payment_print", args=[pay.code])).content.decode()
    assert "Giấy đề nghị tạm ứng" in body and "0123" in body and "(Đã chuyển tiền trên hệ thống" in body
    pm.settle(org.thumua, pay, 11_500_000)
    body = client.get(reverse("payment_print", args=[pay.code])).content.decode()
    assert "Giấy đề nghị thanh toán tạm ứng" in body and "Mười một triệu năm trăm nghìn đồng" in body
    assert "thu mua hoàn lại" in body
    body = client.get(reverse("payment_print", args=[pay.code]) + "?loai=tam-ung").content.decode()
    assert "Giấy đề nghị tạm ứng" in body and "thanh toán tạm ứng" not in body
