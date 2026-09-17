"""读者已知时间线服务（oh-story 双真相：作者真相 vs 读者已知）。

职责：
1. 审批时从章节正文提炼「已向读者揭示」的事实条目
2. 渲染成盲审/写作可注入的「读者已知」块
3. 与 info_boundary（角色视角）互补，检查视角正确性
"""
import json
import logging
import re

from app.models import db, ReaderKnowledge

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "你是小说的连续性编辑。从章节正文提炼「已经向读者明确揭示」的事实，"
    "供后续章节保持视角正确。每条一行，只写读者已经知道的信息；"
    "作者埋了但读者还不知道的秘密不要写入。最多 8 条。"
    "只输出 JSON：{\"facts\":[{\"kind\":\"setting|reveal|secret|character\","
    "\"content\":\"...\"}]}。kind=secret 仅用于「已在正文揭示的秘密」。"
)


def extract_reader_facts(text, cfg):
    """从章节正文提炼读者已知事实；失败返回 []。"""
    text = (text or "").strip()
    if len(text) < 200 or not cfg:
        return []
    from app.services.llm import call_llm_sync, LLMError
    try:
        raw = call_llm_sync(
            model=cfg["model_name"],
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": text[:12000]},
            ],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.2, max_tokens=1000)
    except LLMError as e:
        logger.warning("读者已知提炼失败: %s", e)
        return []
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("读者已知 JSON 解析失败: %s", raw[:120])
        return []
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return []
    cleaned = []
    for f in facts[:8]:
        if not isinstance(f, dict):
            continue
        content = str(f.get("content") or "").strip()
        kind = str(f.get("kind") or "reveal").strip().lower()
        if content and kind in ("setting", "reveal", "secret", "character"):
            cleaned.append({"kind": kind, "content": content})
    return cleaned


def record_reader_facts(novel_id, chapter_number, text, cfg):
    """审批时调用：提炼并落库（幂等——本章已有记录则跳过）。"""
    if ReaderKnowledge.query.filter_by(
            novel_id=novel_id, chapter_number=chapter_number).first():
        return 0
    facts = extract_reader_facts(text, cfg)
    if not facts:
        return 0
    try:
        for f in facts:
            db.session.add(ReaderKnowledge(
                novel_id=novel_id, chapter_number=chapter_number,
                kind=f["kind"], content=f["content"], reader_state="public"))
        db.session.commit()
        return len(facts)
    except Exception as exc:
        logger.warning("读者已知落库失败: %s", exc)
        db.session.rollback()
        return 0


def build_reader_context(novel_id, before_chapter=None, limit=20):
    """渲染「读者已知」块，供盲审/写作注入。

    before_chapter: 只取该章之前（不含）已揭示的事实；None=全部。
    """
    q = ReaderKnowledge.query.filter_by(novel_id=novel_id)
    if before_chapter is not None:
        q = q.filter(ReaderKnowledge.chapter_number < before_chapter)
    rows = q.order_by(ReaderKnowledge.chapter_number.asc()).limit(limit).all()
    if not rows:
        return ""
    lines = ["【读者已知（视角红线：角色不得说出读者还不该知道的事；悬念不得被过早戳破）】"]
    for r in rows:
        tag = {"setting": "设定", "reveal": "揭示", "secret": "已揭示秘密",
               "character": "人物"}.get(r.kind, r.kind)
        lines.append(f"• [第{r.chapter_number}章·{tag}] {r.content}")
    return "\n".join(lines)


def get_public_facts(novel_id, before_chapter=None):
    """结构化取数（供检查/导出）。"""
    q = ReaderKnowledge.query.filter_by(novel_id=novel_id, reader_state="public")
    if before_chapter is not None:
        q = q.filter(ReaderKnowledge.chapter_number < before_chapter)
    return [
        {"chapter": r.chapter_number, "kind": r.kind, "content": r.content}
        for r in q.order_by(ReaderKnowledge.chapter_number.asc()).all()
    ]
