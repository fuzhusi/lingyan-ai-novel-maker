"""提示词构建工具函数：模板加载、上下文组装。"""
import logging

logger = logging.getLogger(__name__)


def _section(title, content):
    if not content:
        return ""
    return f"【{title}】\n{content}"


def get_skill_prompt(task_type="write"):
    """获取活跃技能提示词（供所有 prompt builder 共用）。

    失败时记录警告并返回空串——技能注入永远不能阻断生成，
    但静默吞错会让"生成没用技能"这类问题无从排查。
    """
    try:
        from app.services.skill_system import build_skill_prompt
        return build_skill_prompt(task_type=task_type)
    except Exception:
        logger.warning("build_skill_prompt(%s) failed, skills skipped", task_type,
                       exc_info=True)
        return ""


def _load_system_prompt(db, template_type, fallback):
    """Load system prompt from template library, or return fallback."""
    if db is None:
        return fallback
    from app.models import PromptTemplate
    t = (PromptTemplate.query
         .filter_by(template_type=template_type)
         .order_by(PromptTemplate.id.desc()).first())
    if t and t.template_content and t.template_content.strip():
        return t.template_content.strip()
    return fallback


def _load_constraints(db, template_type):
    """Load writing constraints from template library."""
    if db is None:
        return ""
    from app.models import PromptTemplate
    t = (PromptTemplate.query
         .filter_by(template_type=template_type)
         .order_by(PromptTemplate.id.desc()).first())
    if t and t.constraints and t.constraints.strip():
        return t.constraints.strip()
    return ""


# 默认写作约束 —— 仅作词库(app/services/constraint_bank/)不可用时的应急兜底。
# 完整约束体系已外置到词库（L0 核心/L1 场景/L2 动态文案/L3 词表参考），
# 请勿在此重新堆积规则——单一事实来源在词库文件里；本常量只保留最小应急集。
DEFAULT_WRITER_CONSTRAINTS = """【写作质量约束 — 应急兜底版】
- 严格按给定大纲与详略写：不加引言/总结/小标题，不用"首先/其次"式逻辑词，段落长短参差
- 禁"不是A而是B"及其变体，想清楚直接正面下判断；相邻两句错开句法结构
- 破折号全篇至多两次且禁揭晓式停顿；提示语后不用冒号；对话后不加情绪注解
- 情绪写到动作和身体上不贴标签；内心戏每场景至少一处真实活动
- 比喻、设问是人类写作的自然特征，正常使用不要回避；只输出小说正文
"""


def assemble_chapter_context(novel_id, chapter_number, db, character_ids=None):
    """Gather all relevant context for generating a chapter.

    上下文注入策略（相关性驱动，而非全量堆砌）：
    - character_ids: 本章出场角色 id 列表（前端勾选）；None = 全部角色（兼容旧流程/大纲生成）
    - prev_ending: 上一章结尾原文（~800字），保障章间文风与钩子衔接
    - recent_summaries: 近 3 章详细摘要；earlier_summaries: 更早章节合并压缩摘要
    - 摘要兜底：ChapterSummary 只在审批时生成，直接保存的章节无摘要 ->
      截取正文开头做粗摘要，保证前情提要不为空
    """
    from app.models import (Novel, Character, WorldSetting, OutlineNode,
                            Foreshadowing, Chapter, ChapterSummary)

    novel = Novel.query.get(novel_id)

    # 出场角色过滤：只注入本章登场的角色档案，避免无关角色稀释注意力
    char_query = Character.query.filter_by(novel_id=novel_id)
    if character_ids is not None:
        char_query = char_query.filter(Character.id.in_(character_ids))
    characters = char_query.all()
    characters_data = [
        {
            "name": c.name, "personality": c.personality,
            "speaking_style": c.speaking_style, "appearance": c.appearance,
            "background": c.background, "motivation": c.motivation,
            "arc_direction": c.arc_direction, "status_json": c.status_json,
        }
        for c in characters
    ]

    world_settings = WorldSetting.query.filter_by(novel_id=novel_id).all()
    world_data = [
        {"category": ws.category, "title": ws.title, "content": ws.content}
        for ws in world_settings
    ]

    prev_chapters = (Chapter.query
                     .filter_by(novel_id=novel_id)
                     .filter(Chapter.chapter_number < chapter_number)
                     .order_by(Chapter.chapter_number).all())

    # --- 上章结尾原文：取上一章最新版本正文的末尾 ---
    prev_ending = ""
    if prev_chapters:
        last_ch = prev_chapters[-1]
        if last_ch.versions:
            content = last_ch.versions[-1].content or ""
            prev_ending = ("……" + content[-800:]) if len(content) > 800 else content

    # --- 分层摘要：近 3 章详细 + 更早合并压缩（含无摘要兜底） ---
    def _chapter_summary(ch):
        """取章节摘要；无摘要时用正文开头做粗摘要兜底。"""
        cs = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
        summary = (cs.summary or "").strip() if cs else ""
        if summary:
            return summary
        content = ""
        if ch.versions:
            content = ch.versions[-1].content or ""
        if not content:
            return ""
        return (content[:300] + "……") if len(content) > 300 else content

    recent_summaries = []   # 近 3 章（章节顺序）
    earlier_summaries = []  # 更早章节
    for ch in reversed(prev_chapters):
        text = _chapter_summary(ch)
        if not text:
            continue
        item = {"chapter_number": ch.chapter_number, "summary": text}
        if len(recent_summaries) < 3:
            recent_summaries.append(item)
        else:
            earlier_summaries.append(item)
    recent_summaries.reverse()
    # 更早章节合并为一段并截断（远章只需保持"发生过什么"的粗粒度记忆）
    earlier_merged = ""
    if earlier_summaries:
        earlier_summaries.reverse()  # 恢复章节顺序
        merged = " ".join(
            f"第{s['chapter_number']}章：{s['summary']}" for s in earlier_summaries)
        if len(merged) > 600:
            merged = merged[:600] + "……（更早章节概要已截断）"
        earlier_merged = merged

    # 待回收伏笔：注入所有"未回收/未放弃"状态的伏笔（open→planned→buried→advancing→reclaimable）
    # 仅排除 resolved（已回收）和 abandoned（已放弃）
    foreshadowing_items = Foreshadowing.query.filter_by(
        novel_id=novel_id
    ).filter(
        Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
    ).all()
    foreshadowing_data = [
        {"description": f.description, "planted_chapter": f.planted_chapter,
         "status": f.status, "title": f.title}
        for f in foreshadowing_items
    ]

    outline_node_context = None
    chapter = Chapter.query.filter_by(
        novel_id=novel_id, chapter_number=chapter_number
    ).first()
    if chapter and chapter.outline_node_id:
        node = OutlineNode.query.get(chapter.outline_node_id)
        if node:
            outline_node_context = {
                "node_title": node.title,
                "node_summary": node.summary,
            }
            if node.parent_id:
                parent = OutlineNode.query.get(node.parent_id)
                if parent and parent.node_type == "volume":
                    outline_node_context["volume_title"] = parent.title
                    outline_node_context["volume_summary"] = parent.summary
            scenes = (OutlineNode.query
                      .filter_by(parent_id=node.id, node_type="scene")
                      .order_by(OutlineNode.sort_order).all())
            if scenes:
                outline_node_context["scenes"] = [
                    {"title": s.title, "summary": s.summary} for s in scenes
                ]

    return {
        "characters": characters_data,
        "world_settings": world_data,
        "summaries": recent_summaries,      # 近 3 章详细摘要（兼容旧字段名）
        "earlier_summaries": earlier_merged,  # 更早章节合并压缩摘要
        "prev_ending": prev_ending,          # 上章结尾原文
        "foreshadowing_items": foreshadowing_data,
        "outline_node_context": outline_node_context,
        "genre": novel.genre if novel else "",
        "synopsis": novel.synopsis if novel else "",
        "world_intro": novel.world_intro if novel else "",
    }
