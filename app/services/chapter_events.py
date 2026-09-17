"""本章事件清单（StoryWriter planning 层）。

大纲与正文之间的中间层：从本章大纲提炼 2-4 个必须推进的事件
（目标-冲突-微结局），写作时按事件驱动压缩历史、聚焦戏份。
"""
import json
import logging
import re

from app.models import db, Chapter
from app.models.novel import outline_hash_of

logger = logging.getLogger(__name__)

_EVENT_SYSTEM = (
    "你是小说章节的事件规划编辑。从给定大纲提炼本章必须推进的 2-4 个事件。"
    "每个事件写清：目标（谁要什么）、冲突（挡路的是什么）、微结局（本章结束时状态变化）。"
    "只输出 JSON，不要解释。格式："
    '{"events":[{"goal":"...","conflict":"...","outcome":"..."}]}'
)


def extract_events_from_outline(outline, cfg, max_events=4):
    """用 LLM 从大纲提炼事件清单；失败返回 []（不阻断写作）。"""
    outline = (outline or "").strip()
    if len(outline) < 40 or not cfg:
        return []
    from app.services.llm import call_llm_sync, LLMError
    try:
        raw = call_llm_sync(
            model=cfg["model_name"],
            messages=[
                {"role": "system", "content": _EVENT_SYSTEM},
                {"role": "user", "content": f"本章大纲：\n{outline}\n\n"
                                            f"最多 {max_events} 个事件。"},
            ],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.3, max_tokens=800)
    except LLMError as e:
        logger.warning("事件清单提取失败: %s", e)
        return []
    raw = (raw or "").strip()
    # 容错剥掉 ```json 代码围栏
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("事件清单 JSON 解析失败: %s", raw[:120])
        return []
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        return []
    cleaned = []
    for ev in events[:max_events]:
        if not isinstance(ev, dict):
            continue
        goal = str(ev.get("goal") or "").strip()
        conflict = str(ev.get("conflict") or "").strip()
        outcome = str(ev.get("outcome") or "").strip()
        if goal:
            cleaned.append({"goal": goal, "conflict": conflict, "outcome": outcome})
    return cleaned


def format_events_block(events):
    """渲染为写作包注入块。"""
    if not events:
        return ""
    lines = ["【本章事件清单（硬性推进任务，按事件写戏，不要流水账）】"]
    for i, ev in enumerate(events, 1):
        parts = [f"事件{i}：目标={ev.get('goal', '')}"]
        if ev.get("conflict"):
            parts.append(f"冲突={ev['conflict']}")
        if ev.get("outcome"):
            parts.append(f"微结局={ev['outcome']}")
        lines.append("；".join(parts))
    lines.append("历史上下文按出场实体与上述事件相关性压缩，无关旧章一笔带过。")
    return "\n".join(lines)


def ensure_event_plan(novel_id, chapter_number, outline=None, cfg=None):
    """保证章节已有事件清单；没有则提取并落库。返回事件列表。

    缓存格式：{"outline_hash": "...", "events": [...]}（兼容旧纯 list 格式）。
    大纲变更（hash 不同）时自动重提；提取失败也缓存空列表，避免每次生成重试 LLM。
    """
    chapter = (Chapter.query
               .filter_by(novel_id=novel_id, chapter_number=chapter_number)
               .first())
    if not chapter:
        return []
    outline = outline if outline is not None else (chapter.outline or "")
    outline = (outline or "").strip()
    oh = outline_hash_of(outline)

    if (chapter.event_plan or "").strip():
        try:
            data = json.loads(chapter.event_plan)
            if isinstance(data, dict) and "events" in data:
                if data.get("outline_hash") == oh and isinstance(data["events"], list):
                    return data["events"]
            elif isinstance(data, list):
                # 旧格式：无 hash，视为命中（兼容已有数据）
                return data
        except (json.JSONDecodeError, TypeError):
            pass

    if cfg is None:
        from app.config_utils import get_effective_config
        from app.models import Novel
        novel = Novel.query.get(novel_id)
        cfg = get_effective_config(novel, agent_type="outline")
    events = extract_events_from_outline(outline, cfg)
    try:
        chapter.event_plan = json.dumps(
            {"outline_hash": oh, "events": events}, ensure_ascii=False)
        db.session.commit()
    except Exception as exc:
        logger.warning("事件清单落库失败: %s", exc)
        db.session.rollback()
    return events


def get_event_plan_text(novel_id, chapter_number):
    """读取已落库事件清单并格式化；无则返回空串。"""
    chapter = (Chapter.query
               .filter_by(novel_id=novel_id, chapter_number=chapter_number)
               .first())
    if not chapter or not (chapter.event_plan or "").strip():
        return ""
    try:
        data = json.loads(chapter.event_plan)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(data, dict):
        events = data.get("events") or []
    elif isinstance(data, list):
        events = data
    else:
        events = []
    return format_events_block(events if isinstance(events, list) else [])
