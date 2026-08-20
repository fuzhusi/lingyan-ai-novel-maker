"""提示词构建工具函数：模板加载、上下文组装。"""


def _section(title, content):
    if not content:
        return ""
    return f"【{title}】\n{content}"


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


# Default writing constraints — injected into writer prompts to reduce AI flavor
DEFAULT_WRITER_CONSTRAINTS = """【写作质量约束 — 最高优先级 — 必须严格遵守】

一、禁用词（绝对不能出现）
仿佛、宛如、犹如、恍若、不禁、不由得、眼中闪过、嘴角微微上扬、心中暗想、
一股暖流涌上心头、他知道、他明白、他意识到、他深吸一口气、他缓缓说道、
她轻声道、她微微一笑、目光深邃、意味深长、若有所思、不由自主、情不自禁、
默默地、静静地、轻轻地、缓缓地、微微地（叠词副词大量使用是典型AI特征）

二、句式规则
- 单句不超过 25 字，优先 15 字以内
- 每段不超过 5 句
- 禁止连续 3 句以上用相同句式开头
- 对话后禁止加"他沉声道""她冷笑道"等修饰语，直接写对话或用动作代替
- 少用"的"字连续修饰（"美丽的花朵"→"那朵花"或具体写什么花）
- 长短句交替：连续 2-3 个短句后接一个长句，打破匀称节奏
- 偶尔用碎片句："嗯。""算了。""不对。"打破工整感
- 段落长度不均：有的 2 行，有的 8 行，不要每段都 4-5 行
- 句子中尽量避免使用"不是....是.....","不是....而是...."等连接词。

三、叙事规则
- 用动作和细节代替心理描写（不要写"他很紧张"，写"他的手指在桌面上敲了三下"）
- 感官描写必须具体（不要写"空气中弥漫着香味"，写"空气里有股炸葱花的味道"）
- 禁止用"他知道/明白/意识到"开头的内心独白
- 对话要有潜台词，不要让人物直接说出自己的感受
- 转场用具体的动作或环境变化，不要用"时间流逝""几天后"
- 加入闲笔：写一段看似和主线无关的内容（路边的猫、收音机里的歌、窗台上的灰）
- 不必每件事都解释因果，有时候事情就是发生了
- 不必每段都有总结句，避免结尾升华（"他终于明白了…"）

四、节奏控制
- 高潮场景用短句，描写场景可以适当放长
- 每 500 字至少有一个具体的感官细节（气味/触感/声音/温度）
- 避免每段都是"叙述→对话→心理"的固定结构
- 打破信息密度均匀：有的地方密集推进，有的地方放慢写一个细节

五、风格对比示例（请严格模仿右侧"人味写法"）

【AI 味写法 ✗】→【人味写法 ✓】

"她的眼中闪过一丝复杂的光芒，嘴角微微上扬，意味深长地说道。"
→
"她笑了一下。嘴角微微上扬，轻声到：。"

"他深吸一口气，缓缓说道，语气中带着一丝不易察觉的颤抖。"
→
"他吸了口气。'算了。'"

"空气中弥漫着一种难以言喻的紧张气氛，所有人都若有所思地沉默着。"
→
"谁也没说话。空调嗡嗡响。"

"他心中暗想，这件事一定没有那么简单，一股莫名的不安涌上心头。"
→
"他把烟掐了，又点上一根。"

"她静静地坐在窗边，目光深邃地望着远方，仿佛在思考着什么重要的事情。"
→
"她坐在窗边。楼下有人在吵架。"

"他默默地承受着这一切，内心充满了痛苦和挣扎，但他知道，他必须坚强。"
→
"他没说话。手有点抖。"

"时间悄然流逝，转眼间已是黄昏时分，夕阳的余晖洒在大地上，给一切都镀上了一层金色的光芒。"
→
"天快黑了。他还没回来。"

"她微微一笑，那笑容中带着一丝苦涩，一丝无奈，还有一丝说不清道不明的情感。"
→
"她笑了一下。'没事。'"
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

    foreshadowing_items = Foreshadowing.query.filter_by(
        novel_id=novel_id, status="open"
    ).all()
    foreshadowing_data = [
        {"description": f.description, "planted_chapter": f.planted_chapter}
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
