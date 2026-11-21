from flask import Blueprint, jsonify, request

from app import provisional_store, store
from app.errors import DomainError
from app.modules.m8_provisional import rules

bp = Blueprint("provisional", __name__)


def _linked_row(payload):
    """从既有批次中按run_id/claim_id定位原申报，保留原申报与后续批价的对应关系。"""
    run_id = payload.get("run_id")
    claim_id = str(payload.get("claim_id", "")).strip()
    if not run_id:
        return payload
    try:
        run = store.get(str(run_id).strip())
    except DomainError as error:
        if error.status == 404:
            raise DomainError("UNKNOWN_REFERENCE", "批次不存在或未找到对应申报行", 404)
        raise
    linked = None
    for stage in reversed(run["stages"]):
        for row in stage["rows"]:
            if str(row.get("claim_id", "")).strip() == claim_id:
                linked = row
                break
        if linked:
            break
    if linked is None:
        raise DomainError("UNKNOWN_REFERENCE", "批次内未找到对应申报行", 404)
    merged = dict(linked)
    merged.update({key: value for key, value in payload.items() if value is not None})
    merged["run_id"] = run["run_id"]
    if not merged.get("_sources") and linked.get("_sources"):
        merged["_sources"] = linked["_sources"]
    return merged


@bp.route("/api/provisional", methods=["GET", "POST"])
def confirmations():
    if request.method == "GET":
        items = provisional_store.list_confirmations()
        return jsonify({"rows": items, "metrics": rules.summarize(items)})
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "请求需要对象")
    merged = _linked_row(payload)
    record = rules.confirm_quantity(merged)
    key = record["business_key"]
    try:
        provisional_store.get_confirmation(key)
        created = False
    except DomainError as error:
        if error.status != 404:
            raise
        created = True
    saved = provisional_store.save_confirmation(key, record)
    return jsonify(saved), 201 if created else 200


@bp.get("/api/provisional/<path:business_key>")
def detail(business_key):
    item = provisional_store.get_confirmation(business_key)
    return jsonify({
        "confirmation": item,
        "approvals": provisional_store.list_approvals(business_key),
    })


@bp.post("/api/provisional/<path:business_key>/approval")
def approve(business_key):
    confirmation = provisional_store.get_confirmation(business_key)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload.get("version"), int):
        raise DomainError("BAD_VERSION", "请提供版本号")
    if confirmation.get("status") != "待批价":
        raise DomainError("ALREADY_ADJUDICATED", "该工作量已完成批价，不能重复批价", 409)
    updated = rules.adjudicate_price(confirmation, payload)
    result = provisional_store.apply_approval(
        business_key,
        payload["version"],
        updated,
        {
            "approval_ref": updated["approval_ref"],
            "approved_price": updated["approved_price"],
            "payable_amount": updated["payable_amount"],
            # 固化原申报，批价永远不能覆盖它
            "original_snapshot": confirmation["original_declaration"],
        },
    )
    return jsonify(result)


@bp.get("/api/provisional-approvals")
def approvals():
    return jsonify({"rows": provisional_store.list_approvals()})
