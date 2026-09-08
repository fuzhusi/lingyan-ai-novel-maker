"""提示词构建工具函数：模板加载、上下文组装。"""
import logging

logger = logging.getLogger(__name__)


def _section(title, content):
    if not content:
        return ""
    return f"【{title}】\n{content}"


def get_skill_prompt(task_type="write", extra_skills=None):
    """获取活跃技能提示词（供所有 prompt builder 共用）。

    extra_skills: @skill-id 语法解析出的临时附加技能（仅本次调用生效）。
    失败时记录警告并返回空串——技能注入永远不能阻断生成，
    但静默吞错会让"生成没用技能"这类问题无从排查。
    """
    try:
        from app.services.skill_system import build_skill_prompt
        return build_skill_prompt(task_type=task_type, extra_skills=extra_skills)
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
        "author_intent": (novel.author_intent or "") if novel else "",
        "current_focus": (novel.current_focus or "") if novel else "",
    }


# ---------------------------------------------------------------------------
# 上下文预算渐进压缩（借鉴 OpenWrite 的稳定优先级压缩思路）
# ---------------------------------------------------------------------------

# 默认输入预算（字符数，非 token；中文 1 字 ≈ 1 token，1 字符 = 1 字，留余量）
DEFAULT_CONTEXT_BUDGET = 14000


def build_compass_block(author_intent="", current_focus="", verb="写作时必须兑现"):
    """创作罗盘提示块。writer / outline / rewrite / focus 四条链路共用，
    标签文案单点维护，防止多处手拼逐渐漂移。

    verb: 按链路定制的意图动词（写作时必须兑现 / 修改时必须保持 / 大纲必须服务于此）。
    两项皆空返回空串，调用方按 falsy 跳过。罗盘不参与 apply_context_budget 压缩。
    """
    parts = []
    intent = (author_intent or "").strip()
    focus = (current_focus or "").strip()
    if intent:
        parts.append(f"【作者意图 — 全书承诺，{verb}】\n{intent}")
    if focus:
        parts.append("【当前重心 — 本阶段最高优先级目标】\n" + focus)
    if not parts:
        return ""
    return _section("创作罗盘", "\n\n".join(parts))


def apply_context_budget(kw, budget=DEFAULT_CONTEXT_BUDGET):
    """按稳定优先级渐进收缩上下文，超预算时长记忆先让路。

    收缩顺序（先动最可牺牲的，与 OpenWrite 的渐进压缩哲学一致）：
      1. earlier_summaries  远章概要（粗粒度，全删影响最小）
      2. summaries          近章摘要（3 章 -> 2 章 -> 1 章）
      3. world_settings     世界观补充设定（保留分类标题，砍内容长度）
      4. memory_context     语义检索记忆（FTS 召回是补充性的）
      5. characters         角色档案（砍次要字段，保姓名/性格/动机）

    永不收缩：创作罗盘（author_intent/current_focus）、boundary_context（信息边界
    + 时序真相，一致性红线）、prev_ending（文风衔接）、本章大纲、特别指示、
    伏笔、因果链——这些是"作者意图 + 当前任务 + 精确事实"层。
    返回收缩日志字符串（无收缩返回空串），便于调试与前端提示。
    """
    import json as _json

    def _size():
        n = 0
        n += len(_json.dumps(kw.get("summaries") or [], ensure_ascii=False))
        n += len(kw.get("earlier_summaries") or "")
        n += len(_json.dumps(kw.get("world_settings") or [], ensure_ascii=False))
        n += len(_json.dumps(kw.get("characters") or [], ensure_ascii=False))
        n += len(kw.get("memory_context") or "")
        return n

    log = []
    if _size() <= budget:
        return ""

    # 1) 远章概要整体让路
    if kw.get("earlier_summaries"):
        log.append("远章概要已裁剪（超上下文预算）")
        kw["earlier_summaries"] = ""
        if _size() <= budget:
            return "; ".join(log)

    # 2) 近章摘要逐级降数量（3 -> 2 -> 1 -> 0）
    summaries = kw.get("summaries") or []
    while summaries and _size() > budget:
        dropped = summaries.pop(0)  # 丢最旧的一章
        log.append(f"近章摘要裁掉第{dropped.get('chapter_number', '?')}章")
    if _size() <= budget:
        kw["summaries"] = summaries
        return "; ".join(log)

    # 3) 世界观补充设定：每条内容截断到 200 字
    ws = kw.get("world_settings") or []
    for item in ws:
        content = item.get("content") or ""
        if len(content) > 200:
            item["content"] = content[:200] + "……"
    if ws:
        log.append("世界观补充设定已截断")
        kw["world_settings"] = ws
        if _size() <= budget:
            return "; ".join(log)

    # 4) 语义检索记忆截半
    mc = kw.get("memory_context") or ""
    if mc:
        kw["memory_context"] = mc[:len(mc) // 2] + "\n……（检索记忆已压缩）"
        log.append("语义检索记忆已压缩")
        if _size() <= budget:
            return "; ".join(log)

    # 5) 角色档案：砍次要字段（外貌/背景/弧光），保姓名/性格/说话风格/动机/状态
    chars = kw.get("characters") or []
    minor_fields = ("appearance", "background", "arc_direction")
    if chars:
        for c in chars:
            for f in minor_fields:
                c[f] = ""
        log.append("角色档案次要字段已裁剪")
        kw["characters"] = chars

    return "; ".join(log)
