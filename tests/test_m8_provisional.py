import pytest

from app import provisional_store, store
from app.errors import DomainError
from app.modules.m8_provisional import rules
from app.modules.m8_provisional.handler import bp  # noqa: F401 确保蓝图可导入
from app.pipeline import execute, load_sample


def payload(**overrides):
    base = {
        "claim_id": "ZK-001",
        "period": "2026-11",
        "item": "新增钻孔",
        "unit": "m",
        "confirmed_qty": "120",
        "provisional_price": "85",
        "note": "钻孔作业已完工，新增单价待批",
        "_sources": [42],
    }
    base.update(overrides)
    return base


def test_quantity_confirmed_but_no_payment_without_price_basis():
    "裁决：量照签、价依据缺失时不生成付款金额，暂估只计暂缓"
    record = rules.confirm_quantity(payload())
    assert record["confirmed_qty"] == "120"
    assert record["payable_amount"] == "0.00"
    assert record["held_amount"] == "10200.00"
    assert record["provisional_price"] == "85.00"
    assert record["status"] == "待批价"


def test_held_amount_none_when_no_provisional_price():
    record = rules.confirm_quantity(payload(provisional_price=None))
    assert record["provisional_price"] is None
    assert record["held_amount"] is None
    assert record["payable_amount"] == "0.00"


def test_provisional_sentinel_treated_as_missing():
    record = rules.confirm_quantity(payload(provisional_price="NULL"))
    assert record["provisional_price"] is None and record["held_amount"] is None


def test_negative_or_bad_quantity_rejected():
    with pytest.raises(DomainError) as error:
        rules.confirm_quantity(payload(confirmed_qty="-1"))
    assert error.value.code == "NEGATIVE_QTY"
    with pytest.raises(DomainError) as error:
        rules.confirm_quantity(payload(period="202611"))
    assert error.value.code == "INVALID_PERIOD"


def test_original_declaration_snapshot_is_immutable_after_approval():
    "后续批价生成新版本与付款，原申报快照、已确认量、暂估口径不被覆盖"
    record = rules.confirm_quantity(payload())
    updated = rules.adjudicate_price(
        record, {"version": 1, "approved_price": "96.5", "approval_ref": "PJ-2026-018"}
    )
    assert updated["version"] == 2
    assert updated["status"] == "已批价"
    assert updated["payable_amount"] == "11580.00"
    assert updated["confirmed_qty"] == "120"
    assert updated["held_amount"] == "10200.00"
    assert updated["original_declaration"]["note"] == "钻孔作业已完工，新增单价待批"
    assert updated["original_declaration"]["claim_id"] == "ZK-001"


def test_adjudication_requires_ref_and_non_negative_price():
    record = rules.confirm_quantity(payload())
    with pytest.raises(DomainError) as error:
        rules.adjudicate_price(record, {"version": 1, "approved_price": "90", "approval_ref": ""})
    assert error.value.code == "EMPTY_VALUE"
    with pytest.raises(DomainError) as error:
        rules.adjudicate_price(record, {"version": 1, "approved_price": "-1", "approval_ref": "P"})
    assert error.value.code == "BAD_PRICE"


def test_retry_same_workload_is_idempotent_conflict_raises_409(client):
    "同一工作量重试不重复确认：同载荷幂等，不同载荷409"
    body = {
        "claim_id": "ZK-002", "period": "2026-11", "confirmed_qty": "30",
        "provisional_price": "80",
    }
    first = client.post("/api/provisional", json=body)
    second = client.post("/api/provisional", json=dict(body))
    assert first.status_code == 201 and second.status_code == 200
    assert first.get_json()["business_key"] == second.get_json()["business_key"]
    conflict = client.post("/api/provisional", json=dict(body, confirmed_qty="31"))
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "ALREADY_CONFIRMED"
    assert len(provisional_store.list_confirmations()) == 1


def test_approval_persists_lineage_and_blocks_duplicate(client):
    created = client.post("/api/provisional", json={
        "claim_id": "ZK-003", "period": "2026-11", "confirmed_qty": "10",
        "provisional_price": "50",
    }).get_json()
    key = created["business_key"]
    ok = client.post(f"/api/provisional/{key}/approval", json={
        "version": 1, "approved_price": "60", "approval_ref": "PJ-1",
    })
    assert ok.status_code == 200 and ok.get_json()["payable_amount"] == "600.00"
    duplicate = client.post(f"/api/provisional/{key}/approval", json={
        "version": 2, "approved_price": "70", "approval_ref": "PJ-2",
    })
    assert duplicate.status_code == 409
    assert duplicate.get_json()["code"] == "ALREADY_ADJUDICATED"
    detail = client.get(f"/api/provisional/{key}").get_json()
    approvals = detail["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["from_version"] == 1 and approvals[0]["to_version"] == 2
    # 审批表里固化的原申报不被批价覆盖
    assert approvals[0]["original_snapshot"]["claim_id"] == "ZK-003"
    assert "approved_price" not in approvals[0]["original_snapshot"]
    all_approvals = client.get("/api/provisional-approvals").get_json()["rows"]
    assert len(all_approvals) == 1


def test_failed_switch_keeps_old_version_and_rolls_back(client):
    "切换失败时保留旧版：陈旧版本409，记录维持待批价/V1，且无审批残留"
    created = client.post("/api/provisional", json={
        "claim_id": "ZK-004", "period": "2026-11", "confirmed_qty": "8",
    }).get_json()
    key = created["business_key"]
    stale = client.post(f"/api/provisional/{key}/approval", json={
        "version": 9, "approved_price": "60", "approval_ref": "PJ-9",
    })
    assert stale.status_code == 409 and stale.get_json()["code"] == "STALE_VERSION"
    bad_price = client.post(f"/api/provisional/{key}/approval", json={
        "version": 1, "approved_price": "abc", "approval_ref": "PJ-9",
    })
    assert bad_price.status_code == 422
    unchanged = provisional_store.get_confirmation(key)
    assert unchanged["version"] == 1 and unchanged["status"] == "待批价"
    assert unchanged["payable_amount"] == "0.00"
    assert provisional_store.list_approvals(key) == []
    # 失败后仍可用正确版本完成切换
    ok = client.post(f"/api/provisional/{key}/approval", json={
        "version": 1, "approved_price": "60", "approval_ref": "PJ-10",
    })
    assert ok.status_code == 200 and ok.get_json()["version"] == 2


def test_link_confirmation_to_run_preserves_original_declaration(client):
    "从既有批次定位原申报：原申报字段与来源行随签认固化"
    run = execute(load_sample("dirty.csv"))
    target = run["stages"][3]["rows"][0]
    created = client.post("/api/provisional", json={
        "run_id": run["run_id"], "claim_id": target["claim_id"],
        "period": target["period"], "confirmed_qty": "25",
        "provisional_price": "110",
    })
    assert created.status_code == 201
    record = created.get_json()
    assert record["run_id"] == run["run_id"]
    assert record["source_lines"] == [str(line) for line in target["_sources"]]
    assert record["original_declaration"]["claim_id"] == target["claim_id"]
    assert record["original_declaration"]["unit_price"] == target["unit_price"]


def test_unknown_run_reference_is_404(client):
    response = client.post("/api/provisional", json={
        "run_id": "missing", "claim_id": "X", "period": "2026-11",
        "confirmed_qty": "1",
    })
    assert response.status_code == 404 and response.get_json()["code"] == "UNKNOWN_REFERENCE"


def test_workbench_list_metrics_and_page(client):
    client.post("/api/provisional", json={
        "claim_id": "ZK-005", "period": "2026-11", "confirmed_qty": "10",
        "provisional_price": "80",
    })
    listing = client.get("/api/provisional").get_json()
    assert listing["metrics"]["records"] == 1
    assert listing["metrics"]["pending_price"] == 1
    assert listing["metrics"]["held_total"] == "800.00"
    assert listing["metrics"]["payable_total"] == "0.00"
    page = client.get("/provisional")
    assert page.status_code == 200
    assert "量价分离".encode() in page.data


def test_provisional_uses_isolated_database_and_history_untouched(client):
    before = len(store.history())
    client.post("/api/provisional", json={
        "claim_id": "ZK-006", "period": "2026-11", "confirmed_qty": "5",
    })
    assert len(store.history()) == before
    assert len(provisional_store.list_confirmations()) == 1
