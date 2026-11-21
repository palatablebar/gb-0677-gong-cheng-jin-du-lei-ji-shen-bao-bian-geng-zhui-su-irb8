from datetime import datetime
from decimal import Decimal

from app.config import PROVISIONAL_RULE_VERSION
from app.errors import DomainError
from app.values import SENTINELS, money, number

# 原申报允许固化进快照的字段；批价后也不得改写
SNAPSHOT_FIELDS = (
    "claim_id", "item", "period", "unit", "cumulative_qty", "previous_qty",
    "change_id", "reversal", "reported", "note", "unit_price",
    "increment_qty", "gross_amount",
)


def business_key(claim_id, period):
    claim_id = str(claim_id or "").strip()
    period = str(period or "").strip()
    if not claim_id:
        raise DomainError("EMPTY_VALUE", "申报编号不能为空")
    if not period:
        raise DomainError("EMPTY_VALUE", "申报周期不能为空")
    return claim_id + "|" + period


def _valid_period(value):
    try:
        ok = len(value) == 7 and datetime.strptime(value, "%Y-%m") is not None
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise DomainError("INVALID_PERIOD", "申报周期需为YYYY-MM")
    return value


def confirm_quantity(payload, context=None):
    """裁决：量价分离。

    已完工程量按实签认，避免跨月断档；价格依据缺失时不生成付款金额，
    暂估价仅折算暂缓金额并列明，禁止并入本期签证付款。
    """
    if not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "请求需要对象")
    claim_id = str(payload.get("claim_id", "")).strip()
    period = _valid_period(str(payload.get("period", "")).strip())
    key = business_key(claim_id, period)
    qty = number(payload.get("confirmed_qty"))
    if qty < 0:
        raise DomainError("NEGATIVE_QTY", "签认工程量不能为负")

    provisional_text = None
    held_amount = None
    raw_price = payload.get("provisional_price")
    if raw_price is not None and str(raw_price).strip() not in SENTINELS:
        provisional = number(raw_price)
        if provisional < 0:
            raise DomainError("BAD_PRICE", "暂估价不能为负")
        provisional_text = money(provisional)
        held_amount = money(qty * provisional)

    sources = payload.get("_sources") or []
    if not isinstance(sources, list):
        raise DomainError("BAD_SOURCES", "来源行需要列表")
    snapshot = {
        field: str(payload[field])
        for field in SNAPSHOT_FIELDS
        if payload.get(field) is not None
    }
    return {
        "business_key": key,
        "claim_id": claim_id,
        "period": period,
        "item": str(payload.get("item", "")).strip(),
        "unit": str(payload.get("unit", "")).strip(),
        "confirmed_qty": str(qty),
        "provisional_price": provisional_text,
        "held_amount": held_amount,
        "payable_amount": "0.00",
        "status": "待批价",
        "run_id": str(payload["run_id"]).strip() if payload.get("run_id") else None,
        "source_lines": [str(line) for line in sources],
        "approved_price": None,
        "approval_ref": None,
        "rule_version": PROVISIONAL_RULE_VERSION,
        "original_declaration": snapshot,
    }


def adjudicate_price(confirmation, payload):
    """后续批价：只追加批准版本与付款金额，原申报、已确认量、暂估口径保持不变。"""
    if not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "请求需要对象")
    if confirmation.get("status") != "待批价":
        raise DomainError("ALREADY_ADJUDICATED", "该工作量已完成批价，不能重复批价")
    ref = str(payload.get("approval_ref", "")).strip()
    if not ref:
        raise DomainError("EMPTY_VALUE", "批价依据编号不能为空")
    price = number(payload.get("approved_price"))
    if price < 0:
        raise DomainError("BAD_PRICE", "批准单价不能为负")
    qty = number(confirmation["confirmed_qty"])
    updated = dict(confirmation)
    updated.update({
        "approved_price": money(price),
        "payable_amount": money(qty * price),
        "status": "已批价",
        "approval_ref": ref,
        "version": int(confirmation.get("version", 1)) + 1,
    })
    return updated


def summarize(confirmations):
    held = sum(
        (number(item["held_amount"]) for item in confirmations if item.get("held_amount")),
        Decimal(0),
    )
    payable = sum(
        (number(item["payable_amount"]) for item in confirmations),
        Decimal(0),
    )
    return {
        "records": len(confirmations),
        "pending_price": sum(item.get("status") == "待批价" for item in confirmations),
        "adjudicated": sum(item.get("status") == "已批价" for item in confirmations),
        "held_total": money(held),
        "payable_total": money(payable),
    }
