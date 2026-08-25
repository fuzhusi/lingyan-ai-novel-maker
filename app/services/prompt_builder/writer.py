"""Writer 类提示词构建：章节生成、大纲生成。"""
from app.services.prompt_builder.context import (
    _section, _load_system_prompt, _load_constraints, DEFAULT_WRITER_CONSTRAINTS,
    get_skill_prompt,
)


def build_writer_prompt(novel_title="", chapter_title="", outline="", user_directive="",
                        characters=None, world_settings=None, summaries=None,
                        foreshadowing_items=None, synopsis="", world_intro="",
                        outline_node_context=None, causal_chain="", memory_context="",
                        prev_ending="", earlier_summaries="", genre="", db=None):
    system_prompt = _load_system_prompt(db, "writer", (
        "你是一位专业的小说作家，擅长用生动的语言和细腻的描写创作引人入胜的故事。"
        "根据提供的创作指引，写出高质量的小说章节内容。严格遵守世界观设定和人物设定，"
        "保持人物性格和行为的一致性。"
    ))

    constraints = _load_constraints(db, "writer")
    if not constraints:
        constraints = DEFAULT_WRITER_CONSTRAINTS

    # 技能提示注入到 system message（而非 memory_context）
    skill_prompt = get_skill_prompt("write")

    # 去AI化约束放在 system message 最前面（最高优先级）
    full_system = constraints
    if skill_prompt:
        full_system += "\n\n" + skill_prompt
    full_system += "\n\n" + system_prompt

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))
    if genre:
        blocks.append(_section("小说类型", genre))
    if synopsis:
        blocks.append(_section("小说简介", synopsis))
    if world_intro:
        blocks.append(_section("世界观设定", world_intro))

    if outline_node_context:
        on_parts = []
        if outline_node_context.get("volume_title"):
            on_parts.append(
                f"所属卷：{outline_node_context['volume_title']}\n"
                f"卷概要：{outline_node_context.get('volume_summary', '')}"
            )
        if outline_node_context.get("node_summary"):
            on_parts.append(f"本章规划：{outline_node_context['node_summary']}")
        scenes = outline_node_context.get("scenes", [])
        if scenes:
            scene_lines = []
            for i, s in enumerate(scenes, 1):
                scene_lines.append(f"  幕{i}【{s['title']}】：{s['summary']}")
            on_parts.append("分幕指引：\n" + "\n".join(scene_lines))
        if on_parts:
            blocks.append(_section("大纲树规划", "\n".join(on_parts)))

    if world_settings:
        ws_lines = []
        for ws in world_settings:
            ws_lines.append(f"【{ws['category']} - {ws['title']}】\n{ws['content']}")
        blocks.append(_section("世界观补充设定", "\n\n".join(ws_lines)))

    if characters:
        char_lines = []
        for c in characters:
            parts = [f"姓名：{c.get('name', '')}"]
            for field, label in [
                ("personality", "性格"), ("speaking_style", "说话风格"),
                ("appearance", "外貌"), ("background", "背景"),
                ("motivation", "动机"), ("arc_direction", "角色弧光"),
            ]:
                val = c.get(field, "")
                if val:
                    parts.append(f"{label}：{val}")
            status = c.get("status_json", "{}")
            if status and status != "{}":
                parts.append(f"当前状态：{status}")
            char_lines.append("\n".join(parts))
        blocks.append(_section("人物设定", "\n\n---\n\n".join(char_lines)))

    # 分层记忆：上章结尾原文（衔接）-> 近章详细摘要 -> 更早章节压缩概要
    if prev_ending:
        blocks.append(_section("上一章结尾（原文，请自然衔接文风与情节）", prev_ending))
    if summaries:
        sum_lines = []
        for s in summaries:
            if isinstance(s, dict):
                sum_lines.append(f"第{s.get('chapter_number', '?')}章：{s.get('summary', '')}")
            else:
                sum_lines.append(str(s))
        blocks.append(_section("近章前情提要（最近几章的详细摘要）", "\n".join(sum_lines)))
    if earlier_summaries:
        blocks.append(_section("更早章节概要（粗粒度记忆）", earlier_summaries))

    if foreshadowing_items:
        fs_lines = []
        for f in foreshadowing_items:
            title = f.get("title") or ""
            desc = f.get("description") or ""
            status = f.get("status") or "open"
            planted = f.get("planted_chapter")
            label = f"[{title}] " if title else ""
            planted_note = f"（第{planted}章埋）" if planted else ""
            fs_lines.append(f"• {label}{desc}{planted_note} [{status}]")
        blocks.append(_section("待回收伏笔（请在写作中自然融入，勿遗忘）", "\n".join(fs_lines)))

    if causal_chain:
        blocks.append(_section("因果链（前几章的因果关系，请延续逻辑）", causal_chain))

    if memory_context:
        blocks.append(_section("相关记忆（语义检索结果）", memory_context))

    if chapter_title:
        blocks.append(_section("章节标题", chapter_title))
    if outline:
        blocks.append(_section("本章大纲", outline))

    if user_directive:
        blocks.append(_section("特别指示 - 最高优先级", user_directive))

    blocks.append(_section(
        "字数要求",
        "本章正文目标约 2500 字（不得低于 2000 字）。"
        "请充分展开场景、对话与心理描写，宁可细节丰盈，不可草草收束。"))
    blocks.append("\n请直接输出本章的小说正文内容。")

    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]


def build_outline_prompt(novel_title="", genre="", synopsis="", world_intro="",
                         chapter_title="", chapter_number=1, characters=None,
                         summaries=None, foreshadowing_items=None, db=None):
    system_prompt = _load_system_prompt(db, "outline", (
        "你是一位资深小说大纲策划师，擅长根据小说的设定和背景，为章节制定详细的大纲。"
        "请输出一份结构清晰的章节大纲，包含以下部分："
        "1. 本章核心事件（2-3个关键情节点）"
        "2. 人物出场安排（哪些人物会出现，他们做什么）"
        "3. 情感/氛围基调"
        "4. 与前后文的衔接点"
        "请输出纯文本大纲，不要输出小说正文。"
    ))

    # 大纲也吃节奏类技巧（钩子/张弛），但跳过页面级笔法协议包（正文级技法对大纲是噪音）
    skill_prompt = get_skill_prompt("outline")
    if skill_prompt:
        system_prompt = system_prompt + "\n\n" + skill_prompt

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))
    if genre:
        blocks.append(_section("小说类型", genre))
    if synopsis:
        blocks.append(_section("小说简介", synopsis))
    if world_intro:
        blocks.append(_section("世界观设定", world_intro))
    if chapter_title:
        blocks.append(_section("章节标题", chapter_title))
    blocks.append(_section("章节序号", f"第{chapter_number}章"))

    if characters:
        char_lines = []
        for c in characters:
            parts = [f"姓名：{c.get('name', '')}"]
            for field, label in [
                ("personality", "性格"), ("speaking_style", "说话风格"),
                ("background", "背景"), ("motivation", "动机"),
            ]:
                val = c.get(field, "")
                if val:
                    parts.append(f"{label}：{val}")
            char_lines.append("\n".join(parts))
        blocks.append(_section("现有人物", "\n\n---\n\n".join(char_lines)))

    if summaries:
        sum_lines = []
        for s in summaries:
            if isinstance(s, dict):
                sum_lines.append(f"第{s.get('chapter_number', '?')}章：{s.get('summary', '')}")
            else:
                sum_lines.append(str(s))
        blocks.append(_section("前情提要", "\n".join(sum_lines)))

    if foreshadowing_items:
        fs_lines = [f"• {f['description']}" for f in foreshadowing_items]
        blocks.append(_section("待回收伏笔", "\n".join(fs_lines)))

    blocks.append("\n请为这一章输出详细大纲。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]
