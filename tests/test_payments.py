import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from proposals import attachments
from proposals import payments as pm
from proposals import workflow as wf
from proposals.models import Attachment, PaymentRequest, Proposal

PS = PaymentRequest.Status
K = PaymentRequest.Kind
S = Proposal.Status


def approved(org, total=5_000_000):
    p = wf.create(org.nv_kt, "Máy in", "Hỏng", [{"name": "Máy in", "quantity": Decimal(1), "unit_price": total}])
    p = wf.approve(org.tp_kt, p)
    p = wf.approve(org.gd1, p)
    if p.status == S.CHO_CHU_TICH:
        p = wf.approve(org.ct, p)
    assert p.status == S.DA_DUYET
    return p


def invoice(name="hoa-don.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def pending(user):
    return set(PaymentRequest.objects.filter(pm.pending_q(user)).values_list("code", flat=True))


def test_buyer_sees_approved_proposal_until_payment_created(org):
    p = approved(org)
    assert p.code in set(Proposal.objects.filter(wf.pending_q(org.thumua)).values_list("code", flat=True))
    assert wf.actions_for(org.thumua, p) == [wf.REQUEST_MONEY]
    assert wf.REQUEST_MONEY not in wf.actions_for(org.ketoan, p)
    pm.create(org.thumua, p, K.TAM_UNG, 5_000_000)
    assert p.code not in set(Proposal.objects.filter(wf.pending_q(org.thumua)).values_list("code", flat=True))


def test_advance_full_path(org):
    p = approved(org, 3_000_000)  # dưới mốc vẫn phải qua Chủ tịch
    pay = pm.create(org.thumua, p, K.TAM_UNG, 3_000_000, "Mua ở X")
    assert pay.code.startswith("TU-") and pay.status == PS.CHO_CHU_TICH_UNG
    assert pay.bank_account_number == "0123"  # chụp tài khoản lúc gửi
    assert pending(org.ct) == {pay.code} and pending(org.ketoan) == set()

    pay = pm.approve(org.ct, pay)
    assert pay.status == PS.CHO_CHUYEN_TIEN and pending(org.ketoan) == {pay.code}
    with pytest.raises(wf.WorkflowError):
        pm.transfer(org.ct, pay)  # chỉ kế toán chuyển tiền
    pay = pm.transfer(org.ketoan, pay, "UNC số 12")
    assert pay.status == PS.DANG_MUA and pending(org.thumua) == {pay.code}

    pay = pm.settle(org.thumua, pay, 2_800_000, "Rẻ hơn dự kiến", [invoice()])
    assert pay.status == PS.CHO_DUYET_HOAN_UNG and pay.difference == 200_000
    assert pending(org.ct) == {pay.code}
    pay = pm.approve(org.ct, pay)
    assert pay.status == PS.HOAN_TAT
    p.refresh_from_db()
    assert p.status == S.HOAN_THANH
    actions = list(pay.logs.values_list("action", flat=True))
    assert actions == ["submit", "approve", "transfer", "settle", "approve"]
    assert pay.logs.filter(proposal=p).count() == 5  # lịch sử đề xuất thấy cả phần tiền


def test_self_advance_full_path_requires_invoice(org):
    p = approved(org)
    with pytest.raises(wf.WorkflowError, match="hóa đơn"):
        pm.create(org.thumua, p, K.THANH_TOAN, 4_900_000)
    assert not PaymentRequest.objects.exists() and not Attachment.objects.exists()
    pay = pm.create(org.thumua, p, K.THANH_TOAN, 4_900_000, files=[invoice()])
    assert pay.code.startswith("TT-") and pay.status == PS.CHO_KE_TOAN
    assert pending(org.ketoan) == {pay.code} and pending(org.ct) == set()
    with pytest.raises(wf.WorkflowError):
        pm.approve(org.ct, pay)  # kế toán trước
    pay = pm.approve(org.ketoan, pay)
    assert pay.status == PS.CHO_CHU_TICH_CHI
    pay = pm.approve(org.ct, pay)
    assert pay.status == PS.HOAN_TAT
    p.refresh_from_db()
    assert p.status == S.HOAN_THANH


def test_only_buyer_can_request_and_only_once(org):
    p = approved(org)
    with pytest.raises(wf.WorkflowError):
        pm.create(org.ketoan, p, K.TAM_UNG, 1)
    pay = pm.create(org.thumua, p, K.TAM_UNG, 1_000)
    with pytest.raises(wf.WorkflowError):
        pm.create(org.thumua, p, K.TAM_UNG, 1_000)  # đã có phiếu đang chạy
    pm.cancel(org.thumua, pay)
    assert pm.create(org.thumua, p, K.THANH_TOAN, 1_000, files=[invoice()]).status == PS.CHO_KE_TOAN


def test_cannot_request_before_approval(org):
    p = wf.create(org.nv_kt, "x", "y", [{"name": "a", "quantity": Decimal(1), "unit_price": 1}])
    with pytest.raises(wf.WorkflowError):
        pm.create(org.thumua, p, K.TAM_UNG, 1)


def test_buyer_needs_bank_account(org):
    org.thumua.bank_account_number = ""
    org.thumua.save()
    with pytest.raises(wf.WorkflowError, match="tài khoản"):
        pm.create(org.thumua, approved(org), K.TAM_UNG, 1)


def test_return_and_resubmit(org):
    p = approved(org)
    pay = pm.create(org.thumua, p, K.THANH_TOAN, 1_000, files=[invoice()])
    with pytest.raises(wf.WorkflowError):
        pm.return_(org.ketoan, pay, " ")
    pay = pm.return_(org.ketoan, pay, "Hóa đơn mờ")
    assert pay.status == PS.TRA_VE and pending(org.thumua) == {pay.code}
    assert pm.actions_for(org.thumua, pay) == [pm.EDIT, pm.CANCEL]
    old = pay.attachments.get()
    pay = pm.resubmit(org.thumua, pay, 1_200, "Chụp lại", [invoice("ro.pdf")], [old.pk])
    assert pay.status == PS.CHO_KE_TOAN and pay.amount == 1_200
    assert list(pay.attachments.values_list("name", flat=True)) == ["ro.pdf"]
    with pytest.raises(wf.WorkflowError, match="hóa đơn"):  # không được xóa hết hóa đơn
        pm.return_(org.ketoan, pay, "x")
        pm.resubmit(org.thumua, pay, 1_200, "", [], [pay.attachments.get().pk])


def test_settlement_return_goes_back_to_buying(org):
    pay = pm.create(org.thumua, approved(org), K.TAM_UNG, 1_000)
    pay = pm.transfer(org.ketoan, pm.approve(org.ct, pay))
    pay = pm.settle(org.thumua, pay, 900)
    pay = pm.return_(org.ct, pay, "Thiếu hóa đơn")
    assert pay.status == PS.DANG_MUA
    assert pm.actions_for(org.thumua, pay) == [pm.SETTLE]


def test_cancel_only_before_first_approval(org):
    pay = pm.create(org.thumua, approved(org), K.TAM_UNG, 1_000)
    with pytest.raises(wf.WorkflowError):
        pm.cancel(org.ketoan, pay)
    pay = pm.approve(org.ct, pay)
    with pytest.raises(wf.WorkflowError):
        pm.cancel(org.thumua, pay)  # đã duyệt, chờ chuyển tiền


def test_timeline_and_proposal_waiting_on(org):
    p = approved(org)
    pay = pm.create(org.thumua, p, K.TAM_UNG, 1_000)
    steps = pm.timeline(pay, org.ct)
    assert [s["state"] for s in steps] == ["done", "now", "todo", "todo", "todo"]
    assert steps[1]["meta"] == "Đang chờ bạn"
    p = Proposal.objects.prefetch_related("payments").get(pk=p.pk)
    assert p.waiting_on == "Chủ tịch"
    assert p.status_label == "Chờ Chủ tịch duyệt tạm ứng"
    assert wf.timeline(p, org.ct)[-4]["title"] == "Chủ tịch duyệt tạm ứng"


# ---------- Màn hình ----------

def test_payment_views_flow(client, org):
    p = approved(org)
    client.force_login(org.thumua)
    body = client.get(reverse("proposal_detail", args=[p.code])).content.decode()
    assert "Xin tạm ứng" in body
    assert client.get(reverse("payment_create", args=[p.code]) + "?loai=thanh-toan").status_code == 200
    r = client.post(reverse("payment_create", args=[p.code]),
                    {"loai": "thanh-toan", "amount": "4.900.000", "note": "", "files": [invoice()]})
    pay = PaymentRequest.objects.get()
    assert r.status_code == 302 and pay.amount == 4_900_000 and pay.kind == K.THANH_TOAN

    client.force_login(org.ketoan)
    assert pay.code in client.get(reverse("home")).content.decode()
    client.post(reverse("payment_act", args=[pay.code]), {"action": "approve"})
    client.force_login(org.ct)
    body = client.get(reverse("payment_detail", args=[pay.code])).content.decode()
    assert "Duyệt và hoàn tiền" in body and "0123" in body
    client.post(reverse("payment_act", args=[pay.code]), {"action": "approve"})
    pay.refresh_from_db()
    assert pay.status == PS.HOAN_TAT


def test_settle_view_and_transfer_with_file(client, org):
    pay = pm.approve(org.ct, pm.create(org.thumua, approved(org), K.TAM_UNG, 2_000_000))
    client.force_login(org.ketoan)
    client.post(reverse("payment_act", args=[pay.code]), {"action": "transfer", "files": [invoice("unc.pdf")]})
    pay.refresh_from_db()
    assert pay.status == PS.DANG_MUA and pay.attachments.filter(name="unc.pdf").exists()
    client.force_login(org.thumua)
    assert client.get(reverse("payment_settle", args=[pay.code])).status_code == 200
    client.post(reverse("payment_settle", args=[pay.code]), {"spent": "2.100.000", "note": ""})
    pay.refresh_from_db()
    assert pay.status == PS.CHO_DUYET_HOAN_UNG and pay.spent == 2_100_000 and pay.shortfall == 100_000


def test_payment_list_and_visibility(client, org):
    pay = pm.create(org.thumua, approved(org), K.TAM_UNG, 1_000)
    client.force_login(org.ketoan)
    assert pay.code in client.get(reverse("payment_list")).content.decode()
    body = client.get(reverse("payment_list"), {"loai": "thanh_toan"}, HTTP_HX_REQUEST="true").content.decode()
    assert pay.code not in body and "<html" not in body
    client.force_login(org.nv_kd)  # phòng khác
    assert client.get(reverse("payment_detail", args=[pay.code])).status_code == 404


def test_nav_money_tab_only_for_money_roles(client, org):
    link = f'href="{reverse("payment_list")}"'
    client.force_login(org.ketoan)
    assert link in client.get(reverse("profile")).content.decode()
    client.force_login(org.nv_kt)
    assert link not in client.get(reverse("profile")).content.decode()


def test_profile_bank_self_edit(client, org):
    client.force_login(org.thumua)
    client.post(reverse("profile"), {"bank_name": "ACB", "bank_account_number": "999", "bank_account_holder": "VU",
                                     "next": "https://evil.example/"})
    org.thumua.refresh_from_db()
    assert org.thumua.bank_account_number == "999"


# ---------- File đính kèm ----------

def test_attachment_download_is_permission_checked(client, org):
    p = wf.create(org.nv_kt, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}],
                  files=[invoice("bao-gia.pdf")])
    att = p.attachments.get()
    client.force_login(org.tp_kt)
    r = client.get(reverse("attachment", args=[att.pk]))
    assert r.status_code == 200 and b"".join(r.streaming_content).startswith(b"%PDF")
    assert "inline" in r["Content-Disposition"]
    client.force_login(org.nv_kd)
    assert client.get(reverse("attachment", args=[att.pk])).status_code == 404


def test_upload_validation():
    bad = SimpleUploadedFile("x.exe", b"MZ")
    big = SimpleUploadedFile("a.pdf", b"0")
    big.size = attachments.MAX_SIZE + 1
    errs = attachments.validate([bad, big])
    assert len(errs) == 2


def test_big_photo_is_shrunk(org):
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "red").save(buf, "JPEG")
    photo = SimpleUploadedFile("anh.JPG", buf.getvalue(), content_type="image/jpeg")
    p = wf.create(org.nv_kt, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}], files=[photo])
    att = p.attachments.get()
    with Image.open(att.file.path) as img:
        assert max(img.size) == attachments.MAX_SIDE
    assert att.is_image and att.name == "anh.JPG"


def test_resubmit_proposal_can_remove_files(org):
    p = wf.create(org.nv_kt, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}],
                  files=[invoice("a.pdf"), invoice("b.pdf")])
    p = wf.return_(org.tp_kt, p, "x")
    a = p.attachments.get(name="a.pdf")
    wf.resubmit(org.nv_kt, p, "Ghế", "Hỏng", [{"name": "Ghế", "quantity": Decimal(1), "unit_price": 1}], [], [a.pk])
    assert list(p.attachments.values_list("name", flat=True)) == ["b.pdf"]
