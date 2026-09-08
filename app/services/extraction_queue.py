"""抽取待确认队列（A4 / P2）——自动抽取的事实先进队列，人工核验才写回真源。

kind: "truth"（时序真相）；resolve 时按 kind 回放对应的真源写入。
后续 causal_chain 等抽取源接入时复用同一队列。
"""
import json
import logging

from app import db
from app.models import PendingExtraction

logger = logging.getLogger(__name__)


def queue_extractions(novel_id, kind, payloads, chapter_number=None):
    """批量入队。payloads 为 dict 列表；返回入队数量。"""
    n = 0
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        item = PendingExtraction(
            novel_id=novel_id, kind=kind,
            payload_json=json.dumps(payload, ensure_ascii=False),
            chapter_number=chapter_number,
        )
        db.session.add(item)
        n += 1
    if n:
        db.session.commit()
    return n


def list_pending(novel_id, kind=None):
    """待确认列表（仅 pending 状态）。"""
    q = PendingExtraction.query.filter_by(novel_id=novel_id, status="pending")
    if kind:
        q = q.filter_by(kind=kind)
    items = q.order_by(PendingExtraction.id.asc()).all()
    return [{
        "id": it.id, "kind": it.kind, "status": it.status,
        "chapter_number": it.chapter_number,
        "payload": json.loads(it.payload_json or "{}"),
        "created_at": it.created_at,
    } for it in items]


def resolve_extraction(item_id, adopt):
    """核验一条：adopt=True 写回真源，False 丢弃。

    Returns:
        (ok: bool, message: str)
    """
    item = PendingExtraction.query.get(item_id)
    if not item or item.status != "pending":
        return False, "条目不存在或已处理"
    payload = json.loads(item.payload_json or "{}")

    if adopt and item.kind == "truth":
        try:
            from app.services.temporal_truth import add_truth
            add_truth(
                item.novel_id,
                payload.get("subject", ""),
                payload.get("property", "status"),
                payload.get("value", ""),
                payload.get("from_chapter") or item.chapter_number or 1,
            )
        except Exception as e:
            logger.error("真源回放失败: %s", e, exc_info=True)
            return False, f"真源回放失败：{e}"
    elif adopt:
        return False, f"kind={item.kind} 暂不支持自动回放，请人工处理"

    item.status = "adopted" if adopt else "discarded"
    db.session.commit()
    return True, "已采纳" if adopt else "已丢弃"
