"""章节审批事务（Web / MCP / CLI 共用入口）。

审批语义的单一真源：空内容拒绝 -> 置 approved -> 摘要与结构化记忆（可选，
LLM 失败自动降级兜底）-> 推进故事状态 -> 单次提交。三个入口各自只做协议
适配，不再各写一份逻辑，防止「已审批无正文」「已审批无摘要」的不一致状态。
"""
import json
import logging

from app import db
from app.config_utils import get_effective_config
from app.models import ChapterMemory, ChapterSummary, Character, StoryState
from app.services.llm import call_llm_sync, LLMError
from app.services.prompt_builder import build_summary_prompt

logger = logging.getLogger(__name__)


class EmptyChapterError(Exception):
    """版本正文为空，拒绝审批。"""


def create_version_record(novel_id, chapter_number, content, source,
                          prompt_used="", model_params_json="{}"):
    """创建章节版本的单一入口（Web save-version / MCP save_chapter_content /
    chapter_runner 共用）：清洗 + AI 后处理 + 大纲指纹打点。

    Raises:
        ValueError: 章节不存在。
    """
    from app.models import Chapter, ChapterVersion
    from app.models.novel import outline_hash_of
    from app.services.text_cleaner import clean_ai_text

    content = clean_ai_text(content)
    if source == "ai" and content:
        from app.services.deai_agent import deai_process
        content = deai_process(content)

    chapter = (Chapter.query
               .filter_by(novel_id=novel_id, chapter_number=chapter_number)
               .first())
    if not chapter:
        raise ValueError(f"第{chapter_number}章不存在")

    max_ver = (db.session.query(db.func.max(ChapterVersion.version_number))
               .filter_by(chapter_id=chapter.id).scalar())
    # 记录本次正文所依据的大纲指纹：之后改大纲 → outline_stale() 失配提示
    chapter.outline_hash = outline_hash_of(chapter.outline)
    version = ChapterVersion(
        chapter_id=chapter.id,
        version_number=(max_ver or 0) + 1,
        content=content,
        source=source,
        prompt_used=prompt_used,
        model_params_json=model_params_json,
    )
    db.session.add(version)
    db.session.commit()
    return version


def extract_json_dict(text):
    """从 LLM 输出中提取 JSON 对象：剥 ```json 围栏 → json.loads → 校验为 dict。

    全库统一的解析入口（此前 4 处各自实现且口径不一）。
    Returns:
        dict 或 None（非对象/解析失败）
    """
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        inner = [l for l in lines[1:] if not l.strip().startswith("```")]
        t = "\n".join(inner)
    try:
        data = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _build_memory_prompt(chapter_content="", chapter_number=0, novel_title="", characters=None):
    """Build prompt for structured chapter memory generation."""
    char_names = ", ".join(c.name for c in characters) if characters else ""

    system_prompt = (
        "你是一位小说分析专家。请分析章节内容，提取结构化记忆信息。"
        "输出严格的JSON格式，不要输出其他内容。"
    )
    user_prompt = (
        f"小说：{novel_title}\n"
        f"第{chapter_number}章\n"
        f"已知角色：{char_names}\n\n"
        f"章节正文：\n{chapter_content}\n\n"
        "请提取以下信息并输出JSON：\n"
        '{"summary": "200字以内章节摘要", '
        '"style_note": "30字以内：本章最突出的文体特征（句式/意象/对话密度），供后续章节延续", '
        '"key_events": ["事件1", "事件2", ...], '
        '"character_changes": {"角色名": "变化描述", ...}, '
        '"foreshadow_events": [{"description": "伏笔相关事件", "foreshadow_id": null}], '
        '"new_characters": ["新出场角色名", ...], '
        '"scenes": [{"setting": "场景地点", "characters": ["角色1"], "summary": "50字场景摘要"}, ...]}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def approve_chapter_version(version, generate_summary=True):
    """审批一个 ChapterVersion，返回 {"approved": True, "summary": str}。

    generate_summary=True（Web 审批语义）：同步生成 LLM 摘要 + 结构化记忆，
    LLM 失败时截取正文开头 300 字兜底，前情提要链路不断。
    generate_summary=False（MCP/CLI 历史语义）：仅标记 approved——无摘要时
    前情提要由 assemble_chapter_context 的正文开头截取兜底，不会断。

    Raises:
        EmptyChapterError: 正文为空（三入口统一拒绝，防「已审批无正文」）。
    """
    if not (version.content or "").strip():
        raise EmptyChapterError("正文为空，无法审批")
    version.approved = True
    chapter = version.chapter
    summary_text = ""

    if generate_summary:
        # Generate chapter summary automatically
        try:
            cfg = get_effective_config(chapter.novel, agent_type="summary")
            messages = build_summary_prompt(
                chapter_content=version.content,
                novel_title=chapter.novel.title,
                db=db,
            )
            summary_text = call_llm_sync(
                model=cfg["model_name"], messages=messages,
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=cfg.get("temperature", 0.5), max_tokens=cfg.get("max_tokens", 1024),
            )
        except LLMError:
            summary_text = ""
        except Exception:
            summary_text = ""

        # 摘要兜底：LLM 失败时截取正文开头做粗摘要，保证前情提要链路不断
        if not summary_text.strip():
            content = version.content or ""
            summary_text = (content[:300] + "……") if len(content) > 300 else content

        cs = ChapterSummary.query.filter_by(chapter_id=chapter.id).first()
        if cs:
            cs.summary = summary_text
        else:
            cs = ChapterSummary(chapter_id=chapter.id, summary=summary_text)
            db.session.add(cs)

        # Generate structured chapter memory
        try:
            memory_cfg = get_effective_config(chapter.novel, agent_type="memory")
            memory_prompt = _build_memory_prompt(
                chapter_content=version.content,
                chapter_number=chapter.chapter_number,
                novel_title=chapter.novel.title,
                characters=Character.query.filter_by(novel_id=chapter.novel_id).all(),
            )
            memory_text = call_llm_sync(
                model=memory_cfg["model_name"], messages=memory_prompt,
                api_key=memory_cfg.get("api_key", ""), base_url=memory_cfg.get("base_url", ""),
                provider_type=memory_cfg.get("provider_type", "deepseek"),
                temperature=memory_cfg.get("temperature", 0.5), max_tokens=memory_cfg.get("max_tokens", 1024),
            )
            memory_data = extract_json_dict(memory_text) or {}
        except LLMError:
            memory_data = {}
        except Exception:
            memory_data = {}

        if memory_data:
            cm = ChapterMemory.query.filter_by(chapter_id=chapter.id).first()
            if cm:
                # 防空串覆盖：结构化记忆缺 summary 键时保留既有摘要
                cm.summary = memory_data.get("summary") or cm.summary or summary_text
                cm.key_events_json = json.dumps(memory_data.get("key_events", []), ensure_ascii=False)
                cm.character_changes_json = json.dumps(memory_data.get("character_changes", {}), ensure_ascii=False)
                cm.foreshadow_events_json = json.dumps(memory_data.get("foreshadow_events", []), ensure_ascii=False)
                cm.new_characters_json = json.dumps(memory_data.get("new_characters", []), ensure_ascii=False)
                cm.scenes_json = json.dumps(memory_data.get("scenes", []), ensure_ascii=False)
            else:
                cm = ChapterMemory(
                    novel_id=chapter.novel_id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    summary=memory_data.get("summary", summary_text),
                    key_events_json=json.dumps(memory_data.get("key_events", []), ensure_ascii=False),
                    character_changes_json=json.dumps(memory_data.get("character_changes", {}), ensure_ascii=False),
                    foreshadow_events_json=json.dumps(memory_data.get("foreshadow_events", []), ensure_ascii=False),
                    new_characters_json=json.dumps(memory_data.get("new_characters", []), ensure_ascii=False),
                    scenes_json=json.dumps(memory_data.get("scenes", []), ensure_ascii=False),
                )
                db.session.add(cm)

        # Update story state chapter counter
        story_state = StoryState.query.filter_by(novel_id=chapter.novel_id).first()
        if story_state:
            story_state.current_chapter = max(story_state.current_chapter or 0, chapter.chapter_number)

        # P4 风格备忘录（B3）：逐章累积文体要点，写作包注入后续章节
        style_note = (memory_data.get("style_note") or "").strip()
        if style_note and chapter.novel:
            try:
                memos = json.loads(chapter.novel.style_memo_json or "[]")
                memos.append({"chapter": chapter.chapter_number,
                              "note": style_note[:60]})
                chapter.novel.style_memo_json = json.dumps(memos[-10:], ensure_ascii=False)
            except Exception:
                logger.warning("风格备忘录更新失败", exc_info=True)

    db.session.commit()
    result = {"approved": True, "summary": summary_text}

    # 人工版本 → 反向提取文风锚例候选（用户改过的段落 = 最真人语料，
    # 是否入库由用户在前端确认，零 LLM 成本）
    if version.source == "human":
        try:
            from app.services.style_fingerprint import extract_anchor_candidate
            candidate = extract_anchor_candidate(version.content or "")
            if candidate:
                result["anchor_candidate"] = candidate
        except Exception:
            logger.warning("锚例候选提取失败", exc_info=True)

    return result
