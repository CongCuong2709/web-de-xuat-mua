from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import AppSettings
from proposals import workflow as wf
from proposals.models import ApprovalLog, Proposal

S = Proposal.Status


def items(*prices, qty=1):
    return [{"name": f"Món {i}", "quantity": Decimal(qty), "unit_price": p} for i, p in enumerate(prices, 1)]


def new(org, total=1_000_000, user=None):
    return wf.create(user or org.nv_kt, "Laptop", "Máy cũ hỏng", items(total))


def pending_codes(user):
    return set(Proposal.objects.filter(wf.pending_q(user)).values_list("code", flat=True))


def test_create_sets_code_route_and_log(org):
    p = new(org)
    assert p.code == timezone.localtime().strftime("MS-%Y%m-0001")
    assert new(org).code.endswith("-0002")
    assert p.status == S.CHO_TRUONG_PHONG
    assert p.manager == org.tp_kt and p.department == org.kt
    assert p.total == 1_000_000 and not p.needs_chairman
    assert list(p.logs.values_list("action", flat=True)) == ["submit"]


def test_total_counts_quantity_and_skips_blank_prices(org):
    p = wf.create(org.nv_kt, "VPP", "Cần", [
        {"name": "Bút", "quantity": Decimal("2.5"), "unit_price": 10_000},
        {"name": "Giấy", "quantity": Decimal(3), "unit_price": None},
    ])
    assert p.total == 25_000
    assert p.items.count() == 2


def test_only_staff_with_manager_can_create(org):
    with pytest.raises(wf.WorkflowError):
        wf.create(org.gd1, "x", "y", items(1))  # giám đốc không tạo đơn
    with pytest.raises(wf.WorkflowError):
        wf.create(org.tp_kt, "x", "y", items(1))
    org.nv_kt.manager = None
    org.nv_kt.save()
    with pytest.raises(wf.WorkflowError, match="trưởng phòng"):
        new(org)


def test_under_threshold_path(org):
    p = new(org, 9_999_999)
    assert pending_codes(org.tp_kt) == {p.code}
    assert pending_codes(org.tp_kd) == set()
    p = wf.approve(org.tp_kt, p)
    assert p.status == S.CHO_GIAM_DOC
    assert pending_codes(org.gd1) == pending_codes(org.gd2) == {p.code}
    p = wf.approve(org.gd2, p, "Đồng ý")
    assert p.status == S.DA_DUYET
    assert pending_codes(org.ct) == set()
    assert [(l.action, l.from_status, l.to_status) for l in p.logs.all()] == [
        ("submit", "", S.CHO_TRUONG_PHONG),
        ("approve", S.CHO_TRUONG_PHONG, S.CHO_GIAM_DOC),
        ("approve", S.CHO_GIAM_DOC, S.DA_DUYET),
    ]
    assert p.logs.last().note == "Đồng ý"


def test_threshold_adds_chairman(org):
    p = new(org, 10_000_000)
    assert p.needs_chairman
    p = wf.approve(org.tp_kt, p)
    p = wf.approve(org.gd1, p)
    assert p.status == S.CHO_CHU_TICH
    assert pending_codes(org.ct) == {p.code}
    p = wf.approve(org.ct, p)
    assert p.status == S.DA_DUYET


def test_threshold_is_configurable(org):
    cfg = AppSettings.load()
    cfg.chairman_threshold = 500_000
    cfg.save()
    assert new(org, 600_000).needs_chairman


def test_only_one_director_needed(org):
    p = wf.approve(org.tp_kt, new(org))
    stale = Proposal.objects.get(pk=p.pk)  # giám đốc 2 đang mở cùng đơn
    wf.approve(org.gd1, p)
    with pytest.raises(wf.WorkflowError):
        wf.approve(org.gd2, stale)
    assert p.logs.filter(action="approve").count() == 2


@pytest.mark.parametrize("who", ["tp_kd", "nv_kt", "gd1", "ct", "ketoan", "thumua"])
def test_wrong_person_cannot_approve_at_manager_step(org, who):
    p = new(org)
    with pytest.raises(wf.WorkflowError):
        wf.approve(getattr(org, who), p)
    with pytest.raises(wf.WorkflowError):
        wf.return_(getattr(org, who), p, "lý do")


def test_chairman_cannot_approve_director_step(org):
    p = wf.approve(org.tp_kt, new(org, 20_000_000))
    with pytest.raises(wf.WorkflowError):
        wf.approve(org.ct, p)


def test_return_requires_reason_and_goes_back_to_creator(org):
    p = wf.approve(org.tp_kt, new(org, 20_000_000))
    p = wf.approve(org.gd1, p)
    with pytest.raises(wf.WorkflowError):
        wf.return_(org.ct, p, "   ")
    p = wf.return_(org.ct, p, "Giá cao")
    assert p.status == S.TRA_VE
    assert pending_codes(org.nv_kt) == {p.code}
    assert pending_codes(org.ct) == set()
    assert wf.actions_for(org.nv_kt, p) == [wf.EDIT, wf.CANCEL]
    log = p.logs.last()
    assert (log.action, log.note, log.step_name) == ("return", "Giá cao", "Chủ tịch")


def test_resubmit_restarts_from_manager_and_recomputes(org):
    p = wf.return_(org.tp_kt, new(org, 20_000_000), "Giá cao")
    p = wf.resubmit(org.nv_kt, p, "Laptop rẻ hơn", "Máy cũ hỏng", items(8_000_000))
    assert p.status == S.CHO_TRUONG_PHONG
    assert p.total == 8_000_000 and not p.needs_chairman
    assert p.title == "Laptop rẻ hơn" and p.items.count() == 1
    assert p.code.endswith("-0001")  # mã không đổi
    # trả về nhiều lần không giới hạn
    p = wf.return_(org.tp_kt, p, "Thiếu thông tin")
    p = wf.resubmit(org.nv_kt, p, "Laptop", "Rõ hơn", items(8_000_000))
    assert p.logs.filter(action="resubmit").count() == 2


def test_cannot_resubmit_when_not_returned(org):
    with pytest.raises(wf.WorkflowError):
        wf.resubmit(org.nv_kt, new(org), "a", "b", items(1))


def test_other_staff_cannot_resubmit(org):
    p = wf.return_(org.tp_kt, new(org), "x")
    with pytest.raises(wf.WorkflowError):
        wf.resubmit(org.nv_kd, p, "a", "b", items(1))


def test_cancel_rules(org):
    p = new(org)
    with pytest.raises(wf.WorkflowError):
        wf.cancel(org.tp_kt, p)
    p = wf.cancel(org.nv_kt, p)
    assert p.status == S.DA_HUY
    p2 = wf.approve(org.tp_kt, new(org))
    with pytest.raises(wf.WorkflowError):
        wf.cancel(org.nv_kt, p2)  # đã qua trưởng phòng thì không tự hủy được


def test_visibility(org):
    p = new(org)
    ids = lambda u: set(wf.visible_proposals(u).values_list("pk", flat=True))
    for u in (org.nv_kt, org.tp_kt, org.gd1, org.ct, org.ketoan, org.thumua):
        assert p.pk in ids(u)
    for u in (org.nv_kd, org.tp_kd):
        assert p.pk not in ids(u)


def test_timeline(org):
    p = wf.approve(org.tp_kt, new(org, 20_000_000))
    p = Proposal.objects.get(pk=p.pk)
    steps = wf.timeline(p, org.gd1)
    assert [s["state"] for s in steps] == ["done", "done", "now", "todo", "todo"]
    assert steps[2]["meta"] == "Đang chờ bạn"
    assert wf.timeline(p, org.nv_kt)[2]["meta"] == "Đang chờ"


def test_director_as_manager_approves_once(org):
    from accounts.models import Role
    from proposals.printing import proposal_signatures

    org.gd1.roles.add(Role.objects.get(code=Role.TRUONG_PHONG))
    if hasattr(org.gd1, "_role_codes"):
        del org.gd1._role_codes
    org.nv_kt.manager = org.gd1
    org.nv_kt.save(update_fields=["manager"])

    # Dưới mốc: Giám đốc kiêm Trưởng phòng duyệt 1 lần -> Đã duyệt luôn
    p_low = wf.create(org.nv_kt, "Bút", "Cần", items(1_000_000))
    assert len(wf.timeline(p_low, org.gd1)) == 3  # gửi + GĐ duyệt + Thu mua
    p_low = wf.approve(org.gd1, p_low)
    assert p_low.status == S.DA_DUYET
    sigs, _ = proposal_signatures(Proposal.objects.prefetch_related("logs__actor").get(pk=p_low.pk))
    assert [s["title"] for s in sigs] == ["Người đề xuất", "Giám đốc"]

    # Trên mốc: Giám đốc kiêm Trưởng phòng duyệt 1 lần -> Chờ Chủ tịch
    p_high = wf.create(org.nv_kt, "Server", "Cần", items(20_000_000))
    p_high = wf.approve(org.gd1, p_high)
    assert p_high.status == S.CHO_CHU_TICH
    p_high = wf.approve(org.ct, p_high)
    assert p_high.status == S.DA_DUYET
    sigs, _ = proposal_signatures(Proposal.objects.prefetch_related("logs__actor").get(pk=p_high.pk))
    assert [s["title"] for s in sigs] == ["Người đề xuất", "Giám đốc", "Chủ tịch"]
