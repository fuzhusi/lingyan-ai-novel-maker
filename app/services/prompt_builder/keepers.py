"""Keeper 类提示词构建：角色检查、世界观检查、伏笔检查、编辑润色。"""
from app.services.prompt_builder.context import (
    _section, _load_system_prompt, DEFAULT_WRITER_CONSTRAINTS,
)


def build_character_keeper_prompt(chapter_content="", characters=None, novel_title="", db=None):
    """Character Keeper — checks personality, behavior, growth consistency."""
    system_prompt = _load_system_prompt(db, "character_check", (
        "你是一位角色一致性检查专家。你的职责是检查小说章节中角色的行为、对话、"
        "性格表现是否与设定一致。重点关注：\n"
        "1. 性格一致性：角色的行为是否符合其性格标签\n"
        "2. 说话风格一致性：对话是否符合角色的说话风格设定\n"
        "3. 行为合理性：角色的行为在当前情境下是否合理\n"
        "4. 成长路线：角色的发展是否符合预定的弧光方向\n\n"
        "输出JSON格式：\n"
        '{"pass": true/false, "issues": [{"character": "角色名", "type": "personality/behavior/dialogue/growth", '
        '"description": "问题描述", "severity": "high/medium/low", "suggestion": "修改建议"}]}'
    ))

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))

    if characters:
        char_lines = []
        for c in characters:
            parts = [f"姓名：{c.get('name', '')}"]
            for field, label in [
                ("personality", "性格"), ("speaking_style", "说话风格"),
                ("background", "背景"), ("motivation", "动机"),
                ("arc_direction", "角色弧光"),
            ]:
                val = c.get(field, "")
                if val:
                    parts.append(f"{label}：{val}")
            char_lines.append("\n".join(parts))
        blocks.append(_section("人物设定", "\n\n---\n\n".join(char_lines)))

    blocks.append(_section("章节正文", chapter_content))
    blocks.append("\n请检查角色一致性并输出JSON格式结果。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]


def build_lore_keeper_prompt(chapter_content="", world_settings=None, novel_title="", db=None):
    """Lore Keeper — checks world-building consistency, power levels, rules."""
    system_prompt = _load_system_prompt(db, "lore_check", (
        "你是一位世界观一致性检查专家。你的职责是检查小说章节是否违反已确立的世界观规则。"
        "重点关注：\n"
        "1. 硬冲突：违反物理规则、魔法体系规则等不可违背的设定\n"
        "2. 软冲突：违反社会规则、势力关系等可灵活处理的设定\n"
        "3. 轻微不一致：描写细节略有出入（如地名、距离等）\n\n"
        "输出JSON格式：\n"
        '{"pass": true/false, "issues": [{"type": "hard_conflict/soft_conflict/minor_inconsistency", '
        '"description": "问题描述", "location": "出现位置", "severity": "high/medium/low", '
        '"suggestion": "修改建议"}]}'
    ))

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))

    if world_settings:
        ws_lines = []
        for ws in world_settings:
            ws_lines.append(f"【{ws.get('category', '')} - {ws.get('title', '')}】\n{ws.get('content', '')}")
        blocks.append(_section("世界观设定", "\n\n".join(ws_lines)))

    blocks.append(_section("章节正文", chapter_content))
    blocks.append("\n请检查世界观一致性并输出JSON格式结果。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]


def build_foreshadow_keeper_prompt(chapter_content="", foreshadowing_items=None,
                                    chapter_number=0, novel_title="", db=None):
    """Foreshadow Keeper — checks foreshadowing progress, suggests recoveries."""
    system_prompt = _load_system_prompt(db, "foreshadow_check", (
        "你是一位伏笔管理专家。你的职责是：\n"
        "1. 检查新章节是否推进或回收了已有的伏笔\n"
        "2. 检查是否有伏笔超时未处理\n"
        "3. 建议哪些伏笔适合在后续章节中回收\n\n"
        "输出JSON格式：\n"
        '{"pass": true, "foreshadow_updates": [{"id": 伏笔ID, "new_status": "advancing/reclaimable/resolved", '
        '"reason": "原因"}], "timeout_warnings": [{"id": 伏笔ID, "title": "标题", "age": 章节数}], '
        '"suggestions": [{"id": 伏笔ID, "suggestion": "回收建议"}]}'
    ))

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))
    blocks.append(_section("当前章节号", f"第{chapter_number}章"))

    if foreshadowing_items:
        fs_lines = []
        for f in foreshadowing_items:
            age = chapter_number - f.get("planted_chapter", 0) if f.get("planted_chapter") else 0
            fs_lines.append(
                f"• [ID:{f.get('id', '')}] {f.get('description', '')}"
                f" (状态:{f.get('status', 'open')}, 埋设于第{f.get('planted_chapter', '?')}章, "
                f"已过{age}章, 重要度:{f.get('importance', 5)})"
            )
        blocks.append(_section("活跃伏笔列表", "\n".join(fs_lines)))

    blocks.append(_section("章节正文", chapter_content))
    blocks.append("\n请检查伏笔状态并输出JSON格式结果。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]


def build_editor_prompt(chapter_content="", check_results=None, novel_title="",
                        chapter_title="", outline="", db=None):
    """Editor — final polish based on all keeper check results."""
    from app.services.prompt_builder.context import get_skill_prompt

    system_prompt = _load_system_prompt(db, "editor", (
        "你是一位资深小说编辑。根据各项检查结果，对章节进行最终润色。"
        "你的任务是：\n"
        "1. 修复所有检查发现的问题\n"
        "2. 保持原文的风格和优点\n"
        "3. 确保修改后的文本流畅自然\n"
        "4. 输出修改后的完整章节正文\n\n"
        "只输出修改后的完整章节正文，不要输出其他内容。"
    ))

    # 注入去AI化约束（最高优先级）+ 润色向技能（笔法指纹 + 质检模块）
    full_system = DEFAULT_WRITER_CONSTRAINTS + """

【编辑润色特别注意】
- 不要"修复"文本中的自然不完美（碎片句、口语化表达、不工整的节奏）
- 这些是有意为之的风格特征，不是错误
- 只修复真正的逻辑错误和事实错误，不要"美化"文字
- 保留对话中的语气词、不完整句、打断重叠——这些是人味
- 保留段落的不均匀节奏——这是有意的风格选择
- 如果原文已经很好，不要改动，直接输出原文
"""
    skill_prompt = get_skill_prompt("polish")
    if skill_prompt:
        full_system += "\n\n" + skill_prompt
    full_system += "\n\n" + system_prompt

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))
    if chapter_title:
        blocks.append(_section("章节标题", chapter_title))
    if outline:
        blocks.append(_section("本章大纲", outline))

    if check_results:
        issues_summary = []
        for agent, result in check_results.items():
            if not result.get("pass", True):
                issues = result.get("issues", [])
                issue_lines = [f"  - {i.get('description', '')}" for i in issues]
                issues_summary.append(f"【{agent}】发现 {len(issues)} 个问题：\n" + "\n".join(issue_lines))
        if issues_summary:
            blocks.append(_section("检查发现的问题", "\n\n".join(issues_summary)))

    blocks.append(_section("原文", chapter_content))
    blocks.append("\n请输出润色后的完整章节正文。")

    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]
