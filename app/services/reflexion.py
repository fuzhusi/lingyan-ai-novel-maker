"""跨章 Reflexion（Self-Refine/Reflexion 思路）——收敛失败经验沉淀。

把「本章收敛失败原因 / 盲审弃稿理由」写入章节笔记，下一章生成时注入，
避免同一类错误反复踩。
"""
import logging

from app.models import db, Chapter

logger = logging.getLogger(__name__)

_MAX_LESSONS = 3
_LESSON_MAX_CHARS = 120


def add_reflexion_note(novel_id, chapter_number, note, source="tone"):
    """给章节追加一条反思笔记（去重、截断、上限）。"""
    note = (note or "").strip()[:_LESSON_MAX_CHARS]
    if not note:
        return False
    chapter = (Chapter.query
               .filter_by(novel_id=novel_id, chapter_number=chapter_number)
               .first())
    if not chapter:
        return False
    try:
        import json
        notes = []
        if (chapter.reflexion_notes or "").strip():
            try:
                parsed = json.loads(chapter.reflexion_notes)
                if isinstance(parsed, list):
                    notes = parsed
            except (json.JSONDecodeError, TypeError):
                notes = []
        # 去重
        if any(n.get("note") == note for n in notes if isinstance(n, dict)):
            return False
        notes.append({"source": source, "note": note})
        chapter.reflexion_notes = json.dumps(notes[-_MAX_LESSONS:], ensure_ascii=False)
        db.session.commit()
        return True
    except Exception as exc:
        logger.warning("Reflexion 笔记写入失败: %s", exc)
        db.session.rollback()
        return False


def collect_recent_lessons(novel_id, before_chapter, limit=5):
    """取本章之前最近几章的反思笔记，渲染成注入块。"""
    import json
    rows = (Chapter.query
            .filter(Chapter.novel_id == novel_id,
                    Chapter.chapter_number < before_chapter)
            .order_by(Chapter.chapter_number.desc())
            .limit(12)
            .all())
    lines = []
    for ch in rows:
        if not (ch.reflexion_notes or "").strip():
            continue
        try:
            notes = json.loads(ch.reflexion_notes)
        except (json.JSONDecodeError, TypeError):
            continue
        for n in notes if isinstance(notes, list) else []:
            if isinstance(n, dict) and n.get("note"):
                src = n.get("source", "tone")
                lines.append(f"· 第{ch.chapter_number}章（{src}）：{n['note']}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return ("【前章反思（写本章时主动避开）】\n" + "\n".join(lines[:limit]))


def note_from_convergence(conv_result, novel_id, chapter_number):
    """从 converge_tone 结果提炼反思（失败/回滚时才有价值）。"""
    if not isinstance(conv_result, dict):
        return
    if conv_result.get("converged"):
        return
    rounds = conv_result.get("rounds") or []
    # 找到失败/回滚那一轮的原因
    reason = ""
    for r in rounds:
        action = str(r.get("action", ""))
        if "回滚" in action or "弃用" in action or "失败" in action:
            reason = action
            break
    if not reason:
        reason = conv_result.get("reason") or "收敛未提升人味分"
    add_reflexion_note(novel_id, chapter_number,
                       f"去AI味收敛：{reason}", source="tone")
