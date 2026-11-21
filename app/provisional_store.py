import json
import sqlite3
from datetime import datetime, timezone

from app.config import DATA_DIR
from app.errors import DomainError


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "records.db", timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS provisional_confirmations ("
        "business_key TEXT PRIMARY KEY, payload TEXT NOT NULL, "
        "version INTEGER NOT NULL DEFAULT 1, "
        "status TEXT NOT NULL DEFAULT '待批价', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS price_approvals ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, business_key TEXT NOT NULL, "
        "from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, "
        "approval_ref TEXT NOT NULL, approved_price TEXT NOT NULL, "
        "payable_amount TEXT NOT NULL, original_snapshot TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    return db


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row(cursor_row):
    data = json.loads(cursor_row[0])
    return {
        **data,
        "version": cursor_row[1],
        "status": cursor_row[2],
        "created_at": cursor_row[3],
        "updated_at": cursor_row[4],
    }


def save_confirmation(business_key, record):
    """同一工作量只确认一次：同载荷重试幂等返回，不同载荷冲突拒绝。"""
    stamp = _now()
    with connect() as db:
        existing = db.execute(
            "SELECT payload FROM provisional_confirmations WHERE business_key=?",
            (business_key,),
        ).fetchone()
        if existing:
            if json.loads(existing[0]) == record:
                return get_confirmation(business_key)
            raise DomainError("ALREADY_CONFIRMED", "同一工作量已签认，不能重复确认", 409)
        db.execute(
            "INSERT INTO provisional_confirmations"
            "(business_key,payload,version,status,created_at,updated_at) VALUES (?,?,1,?,?,?)",
            (business_key, json.dumps(record, ensure_ascii=False), record["status"], stamp, stamp),
        )
    return get_confirmation(business_key)


def get_confirmation(business_key):
    with connect() as db:
        row = db.execute(
            "SELECT payload,version,status,created_at,updated_at "
            "FROM provisional_confirmations WHERE business_key=?",
            (business_key,),
        ).fetchone()
    if not row:
        raise DomainError("NOT_FOUND", "暂估签认记录不存在", 404)
    return _row(row)


def list_confirmations():
    with connect() as db:
        rows = db.execute(
            "SELECT payload,version,status,created_at,updated_at "
            "FROM provisional_confirmations"
        ).fetchall()
    return sorted((_row(row) for row in rows), key=lambda item: (item["period"], item["claim_id"]))


def apply_approval(business_key, expected_version, updated, approval):
    """条件更新+同事务追加审批记录；版本不匹配整体回滚，旧版保留。"""
    stamp = _now()
    with connect() as db:
        current = db.execute(
            "SELECT version,status FROM provisional_confirmations WHERE business_key=?",
            (business_key,),
        ).fetchone()
        if not current:
            raise DomainError("NOT_FOUND", "暂估签认记录不存在", 404)
        if current[1] != "待批价":
            raise DomainError("ALREADY_ADJUDICATED", "该工作量已完成批价，不能重复批价", 409)
        if current[0] != expected_version:
            raise DomainError("STALE_VERSION", "版本已更新，请刷新后重试", 409)
        payload = {key: value for key, value in updated.items()
                   if key not in ("version", "status", "created_at", "updated_at")}
        cursor = db.execute(
            "UPDATE provisional_confirmations SET payload=?, version=?, status=?, updated_at=? "
            "WHERE business_key=? AND version=? AND status='待批价'",
            (json.dumps(payload, ensure_ascii=False), updated["version"],
             updated["status"], stamp, business_key, expected_version),
        )
        if cursor.rowcount != 1:
            raise DomainError("STALE_VERSION", "版本已更新，请刷新后重试", 409)
        db.execute(
            "INSERT INTO price_approvals"
            "(business_key,from_version,to_version,approval_ref,approved_price,"
            "payable_amount,original_snapshot,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (business_key, expected_version, updated["version"], approval["approval_ref"],
             approval["approved_price"], approval["payable_amount"],
             json.dumps(approval["original_snapshot"], ensure_ascii=False), stamp),
        )
    return get_confirmation(business_key)


def list_approvals(business_key=None):
    query = ("SELECT business_key,from_version,to_version,approval_ref,approved_price,"
             "payable_amount,original_snapshot,created_at FROM price_approvals")
    args = ()
    if business_key:
        query += " WHERE business_key=?"
        args = (business_key,)
    query += " ORDER BY id"
    with connect() as db:
        rows = db.execute(query, args).fetchall()
    return [
        {
            "business_key": row[0], "from_version": row[1], "to_version": row[2],
            "approval_ref": row[3], "approved_price": row[4], "payable_amount": row[5],
            "original_snapshot": json.loads(row[6]), "created_at": row[7],
        }
        for row in rows
    ]
