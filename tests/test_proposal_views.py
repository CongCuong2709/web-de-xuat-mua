from decimal import Decimal

import pytest
from django.urls import reverse

from core.models import ReturnReason
from proposals import workflow as wf
from proposals.models import Proposal

S = Proposal.Status


def login(client, user):
    client.force_login(user)
    return client


def make(org, price=1_000_000):
    return wf.create(org.nv_kt, "Laptop", "Máy cũ hỏng", [{"name": "Laptop", "quantity": Decimal(1), "unit_price": price}])


def test_create_via_form(client, org):
    login(client, org.nv_kt)
    assert client.get(reverse("proposal_create")).status_code == 200
    r = client.post(reverse("proposal_create"), {
        "title": "Văn phòng phẩm",
        "reason": "Hết giấy",
        "item_name": ["Giấy A4", "Bút", ""],
        "item_qty": ["5", "2,5", "1"],
        "item_price": ["75.000", "10000", ""],
    })
    assert r.status_code == 302
    p = Proposal.objects.get()
    assert p.total == 5 * 75_000 + 25_000
    assert [i.name for i in p.items.all()] == ["Giấy A4", "Bút"]
    assert p.status == S.CHO_TRUONG_PHONG


def test_create_form_errors_keep_input(client, org):
    login(client, org.nv_kt)
    r = client.post(reverse("proposal_create"), {"title": "", "reason": "x", "item_name": ["Bút"], "item_qty": ["abc"], "item_price": ["1"]})
    body = r.content.decode()
    assert r.status_code == 200
    assert "Cần ghi rõ cần mua gì" in body and "số lượng không hợp lệ" in body
    assert r.context["data"]["raw_items"] == [{"name": "Bút", "qty": "abc", "price": "1"}]
    assert not Proposal.objects.exists()


def test_director_cannot_open_create(client, org):
    login(client, org.gd1)
    assert client.get(reverse("proposal_create")).status_code == 403


def test_home_lists_my_pending(client, org):
    p = make(org)
    body = login(client, org.tp_kt).get(reverse("home")).content.decode()
    assert p.code in body and "1 việc đang chờ bạn" in body
    body = login(client, org.gd1).get(reverse("home")).content.decode()
    assert p.code not in body and "Không có việc nào" in body


def test_approve_and_return_via_view(client, org):
    p = make(org)
    login(client, org.tp_kt)
    r = client.post(reverse("proposal_act", args=[p.code]), {"action": "approve"})
    assert r.status_code == 302
    p.refresh_from_db()
    assert p.status == S.CHO_GIAM_DOC

    login(client, org.gd1)
    reason = ReturnReason.objects.first().text
    client.post(reverse("proposal_act", args=[p.code]), {"action": "return", "reason_choice": reason, "note": "Xem lại hãng"})
    p.refresh_from_db()
    assert p.status == S.TRA_VE
    assert p.logs.last().note == f"{reason}. Xem lại hãng"


def test_return_without_reason_rejected(client, org):
    p = make(org)
    login(client, org.tp_kt)
    client.post(reverse("proposal_act", args=[p.code]), {"action": "return", "reason_choice": "", "note": " "})
    p.refresh_from_db()
    assert p.status == S.CHO_TRUONG_PHONG


def test_wrong_user_post_does_nothing(client, org):
    p = make(org)
    login(client, org.ketoan)  # xem được nhưng không duyệt được
    client.post(reverse("proposal_act", args=[p.code]), {"action": "approve"})
    p.refresh_from_db()
    assert p.status == S.CHO_TRUONG_PHONG


def test_detail_hidden_from_other_department(client, org):
    p = make(org)
    assert login(client, org.nv_kd).get(reverse("proposal_detail", args=[p.code])).status_code == 404
    assert login(client, org.ketoan).get(reverse("proposal_detail", args=[p.code])).status_code == 200


def test_detail_shows_actions_only_to_approver(client, org):
    p = make(org)
    body = login(client, org.tp_kt).get(reverse("proposal_detail", args=[p.code])).content.decode()
    assert "Gửi trả về" in body and ">Duyệt<" in body
    body = login(client, org.gd1).get(reverse("proposal_detail", args=[p.code])).content.decode()
    assert "Gửi trả về" not in body
    pane = login(client, org.tp_kt).get(reverse("proposal_detail", args=[p.code]) + "?pane=1").content.decode()
    assert "<html" not in pane and p.code in pane


def test_edit_and_resubmit_via_form(client, org):
    p = wf.return_(org.tp_kt, make(org), "Thiếu thông tin")
    login(client, org.nv_kt)
    body = client.get(reverse("proposal_edit", args=[p.code])).content.decode()
    assert "Thiếu thông tin" in body and "Laptop" in body
    client.post(reverse("proposal_edit", args=[p.code]), {
        "title": "Laptop 14 inch", "reason": "Rõ hơn", "item_name": ["Laptop"], "item_qty": ["1"], "item_price": ["15000000"],
    })
    p.refresh_from_db()
    assert p.status == S.CHO_TRUONG_PHONG and p.needs_chairman and p.title == "Laptop 14 inch"


def test_list_search_and_filter(client, org):
    a = make(org)
    b = wf.create(org.nv_kt, "Ghế làm việc", "Ghế hỏng", [{"name": "Ghế", "quantity": Decimal(3), "unit_price": 1}])
    wf.return_(org.tp_kt, b, "x")
    login(client, org.ketoan)
    body = client.get(reverse("proposal_list"), {"q": "ghế"}).content.decode()
    assert b.code in body and a.code not in body
    body = client.get(reverse("proposal_list"), {"nhom": "cho"}, HTTP_HX_REQUEST="true").content.decode()
    assert a.code in body and b.code not in body and "<html" not in body
    body = client.get(reverse("proposal_list"), {"phong": org.kd.pk}).content.decode()
    assert a.code not in body


def test_list_only_visible(client, org):
    p = make(org)
    body = login(client, org.nv_kd).get(reverse("proposal_list")).content.decode()
    assert p.code not in body


def test_nav_badge(client, org):
    make(org)
    body = login(client, org.tp_kt).get(reverse("profile")).content.decode()
    assert '<b class="badge">1</b>' in body
    assert "Tạo đề xuất" not in body  # trưởng phòng không tạo đơn
