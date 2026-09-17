"""Writer 类提示词构建：章节生成、大纲生成。"""
import logging

from app.services.prompt_builder.context import (
    _section, _load_system_prompt, _load_constraints, DEFAULT_WRITER_CONSTRAINTS,
    get_skill_prompt, build_compass_block,
)

logger = logging.getLogger(__name__)


def build_writer_prompt(novel_title="", chapter_title="", outline="", user_directive="",
                        characters=None, world_settings=None, summaries=None,
                        foreshadowing_items=None, synopsis="", world_intro="",
                        outline_node_context=None, causal_chain="", memory_context="",
                        boundary_context="",
                        prev_ending="", earlier_summaries="", genre="", db=None,
                        tone_instructions="", author_intent="", current_focus="",
                        style_memo="", creator_preferences="", narrative_plan="",
                        reference_passages="", cast_constraint="", chapter_events="",
                        reader_known="", reflexion_lessons=""):
    system_prompt = _load_system_prompt(db, "writer", (
        "你是一位专业的畅销网文作家，具备丰富的网文学创作经验，擅长使用细腻的描写和生动的对话来刻画人物和推动情节发展。"
        "根据提供的创作指引，写出高质量的小说章节内容。严格遵守世界观设定和人物设定，"
        "保持人物性格和行为的一致性。"
    ))

    # 约束来源优先级：DB 模板(用户显式自定义) > 约束词库(按预算装配，见
    # app/services/constraint_bank/) > DEFAULT_WRITER_CONSTRAINTS(兜底)。
    # 词库装配把常驻约束从 1566 字压到 ~800 字以内，且超预算自动裁低优先模块。
    constraints = _load_constraints(db, "writer")
    if not constraints:
        try:
            from app.services.constraint_bank import assemble_constraints
            constraints = assemble_constraints(
                agent_type="writer", genre=genre or None)["text"]
        except Exception:
            logger.warning("constraint bank unavailable, fallback to default",
                           exc_info=True)
            constraints = ""
    if not constraints:
        constraints = DEFAULT_WRITER_CONSTRAINTS

    # 技能提示注入到 system message（而非 memory_context）
    # 特别指示里的 @skill-id 语法：临时附加技能（仅本次生效）
    from app.services.skill_system import parse_directive_skills
    directive_clean, extra_skills = parse_directive_skills(user_directive)
    if directive_clean != user_directive:
        user_directive = directive_clean
    skill_prompt = get_skill_prompt("write", extra_skills=extra_skills)

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

    # 创作罗盘（借鉴 OpenWrite）：位于上下文最高优先位置，永不因 token 预算被裁
    compass = build_compass_block(author_intent, current_focus, verb="写作时必须兑现")
    if compass:
        blocks.append(compass)

    # P4 创作偏好档案：长期有效的结构化约束（文风/禁忌/受众）
    if creator_preferences and creator_preferences.strip():
        blocks.append(_section("创作偏好档案（长期有效，最高优先约束）",
                               creator_preferences.strip()))
    # P4 风格备忘录（B3）：审批时逐章累积的文体要点
    if style_memo and style_memo.strip():
        blocks.append(_section("近期文体备忘（延续已建立的文体走向）",
                               style_memo.strip()))

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

    # 出场角色硬约束（写作页出场勾选透出）：白名单 + 未列入者禁入
    if cast_constraint:
        blocks.append(_section("本章出场角色约束（硬约束，优先级高于大纲与前情）",
                               cast_constraint))

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

    if narrative_plan:
        blocks.append(_section("本章叙事计划（拆书蓝图排程，硬性任务，不是可选提醒）", narrative_plan))

    if chapter_events:
        blocks.append(_section("本章事件清单", chapter_events))

    if reader_known:
        blocks.append(_section("读者已知（已揭示信息，勿重讲；可作戏剧反讽）", reader_known))

    if reflexion_lessons:
        blocks.append(_section("前章反思", reflexion_lessons))

    if reference_passages:
        blocks.append(_section("对标书写法参考（语义检索，仅供技法参考，禁止照抄内容）", reference_passages))

    if causal_chain:
        blocks.append(_section("因果链（前几章的因果关系，请延续逻辑）", causal_chain))

    if memory_context:
        blocks.append(_section("相关记忆（语义检索结果）", memory_context))

    # 信息边界 + 时序真相：一致性红线，独立段落且不在上下文预算压缩范围
    if boundary_context:
        blocks.append(_section("信息边界与既定事实（一致性红线，必须遵守）", boundary_context))

    if chapter_title:
        blocks.append(_section("章节标题", chapter_title))
    if outline:
        blocks.append(_section("本章大纲", outline))
        # 节拍施工指令：大纲含【场景节拍】时，告诉写手节拍是施工顺序——
        # 逐拍铺写成场景，防止把 3-5 拍写成"接着/然后/最后"的梗概流水账。
        # 旧格式大纲（无节拍字段）不受影响。
        if "【场景节拍】" in outline:
            blocks.append(_section(
                "节拍施工指令（硬要求）",
                "本章大纲含【场景节拍】，节拍顺序即本章的施工顺序：逐拍铺写，"
                "每一拍至少落成一个完整场景（动作必备，有人物互动的拍须落到对话），"
                "不得略拍、不得把多拍合并为梗概式叙述；拍与拍之间过渡自然，"
                "大纲含【结尾钩子】时，最后一拍须落在该钩子上。"))

    # 行文指纹修正指令（基于近期章节检测，位于特别指示之前、优先级次高）
    if tone_instructions:
        blocks.append(_section("行文指纹修正", tone_instructions))

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
                         summaries=None, foreshadowing_items=None, db=None,
                         author_intent="", current_focus="", world_settings=None):
    system_prompt = _load_system_prompt(db, "outline", (
        "你是一位资深小说大纲策划师。你输出的每一份章节大纲都必须严格遵守下方的"
        "【章节大纲固定格式】：它是后续自动勾选出场角色、按节拍铺写正文的施工依据，"
        "字段一个都不能少、顺序不能乱、字段名原样保留。\n"
        "\n"
        "章节大纲固定格式：\n"
        "【本章定位】从「推进／转折／揭示／过渡／高潮铺垫」中选一个主定位，"
        "再用一句话说明本章在整个故事中的作用\n"
        "【核心事件】1-3条，每条一句话，写成「谁+做了什么+导致什么结果」；"
        "只写章级因果主线，不要复述【场景节拍】里的细节\n"
        "【出场人物】列出本章有戏份的角色名：若下方列出现有人物，人名必须与其姓名"
        "完全一致（一个字都不能改，因为系统按人名自动勾选出场）；仅被提及不登场的名字后标注"
        "（背景提及）；确需功能性龙套（如店小二）写「龙套（不起名）」，不得给龙套起名；"
        "书中暂无人物档案时全部按龙套处理\n"
        "【场景节拍】3-5条，按时间顺序，每条一句话构成一个独立场景："
        "「地点+在场人物+冲突或动作+场面结果」；若下方世界观设定或前情提要中已有该地点，"
        "地名须与其一致，确无来源时可按世界观风格新造；"
        "写正文时每一拍将铺写成一个场景，是施工顺序\n"
        "【情感基调】本章基调及其迁移过程（例：怀疑→恐惧→决绝）\n"
        "【伏笔操作】结合下方【待回收伏笔】（若有）与既有剧情安排：埋设：…／强化：…／回收：…"
        "（可只写其中一两种）；本章确无伏笔动作写「无」\n"
        "【结尾钩子】一句话写出本章最后一拍留下的悬念，必须让读者想立刻读下一章\n"
        "\n"
        "节奏自检（软指导）：若【前情提要】显示近几章均为高强度推进，本章宜作过渡缓冲；"
        "全篇每3-5章应构成一个含小高潮的悬念单元\n"
        "\n"
        "硬性要求：\n"
        "1. 大纲是施工图不是正文：禁止出现对白、心理描写与环境渲染；"
        "除【场景节拍】外全文不超过250字\n"
        "2. 【出场人物】名单之外的角色一律不得出现在【场景节拍】中；（背景提及）与龙套不算登场\n"
        "3. 输出纯文本大纲，不要输出小说正文，不要解释格式本身"
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

    # 创作罗盘：大纲更不能写歪
    compass = build_compass_block(author_intent, current_focus, verb="大纲必须服务于此")
    if compass:
        blocks.append(compass)

    if world_intro:
        blocks.append(_section("世界观设定", world_intro))
    # 世界观条目：大纲节拍要先于正文定地名，不喂条目模型会自创平行世界地名
    if world_settings:
        ws_lines = []
        for ws in world_settings:
            ws_lines.append(f"【{ws['category']} - {ws['title']}】\n{ws['content']}")
        blocks.append(_section(
            "世界观设定条目（【场景节拍】中的地点、势力、组织名须取自此处或前情提要）",
            "\n\n".join(ws_lines)))
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

    blocks.append("\n请严格按系统要求中的【章节大纲固定格式】输出本章大纲。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]
