"""Review 类提示词构建：评审、摘要、改写。"""
from app.services.prompt_builder.context import (
    _section, _load_system_prompt, DEFAULT_WRITER_CONSTRAINTS,
)


def build_critic_prompt(novel_title="", chapter_title="", chapter_content="",
                        outline="", user_directive="", characters=None,
                        world_settings=None, foreshadowing_items=None, db=None):
    system_prompt = _load_system_prompt(db, "critic", (
        "你是一位资深文学评论编辑，擅长分析小说写作质量。"
        "根据提供的创作指引和章节内容，从以下维度进行评估："
        "1. 文笔质量（语言流畅度、描写细腻度）"
        "2. 人物一致性（性格、说话风格、行为是否符合设定）"
        "3. 世界观一致性（是否符合世界观设定）"
        "4. 情节推进（大纲要求的剧情点是否到位）"
        "5. 伏笔呼应（是否自然融入伏笔）"
        "6. 用户指示完成度（特别指示是否得到充分体现）"
        "\n请输出JSON格式的评审结果，不要输出其他内容。"
    ))

    user_parts = []
    if novel_title:
        user_parts.append(f"【小说名称】\n{novel_title}")
    if world_settings:
        ws_lines = []
        for ws in world_settings:
            ws_lines.append(f"【{ws.get('category', '')} - {ws.get('title', '')}】\n{ws.get('content', '')}")
        user_parts.append(f"【世界观设定参考】\n\n".join(ws_lines))
    if characters:
        char_lines = []
        for c in characters:
            parts = [f"姓名：{c.get('name', '')}"]
            for field, label in [("personality", "性格"), ("speaking_style", "说话风格"), ("motivation", "动机")]:
                val = c.get(field, "")
                if val:
                    parts.append(f"{label}：{val}")
            char_lines.append("\n".join(parts))
        user_parts.append(f"【人物设定参考】\n" + "\n---\n".join(char_lines))
    if chapter_title:
        user_parts.append(f"【章节标题】\n{chapter_title}")
    if outline:
        user_parts.append(f"【本章大纲】\n{outline}")
    if user_directive:
        user_parts.append(f"【特别指示】\n{user_directive}")
    if foreshadowing_items:
        fs_lines = [f"• {f['description']}" for f in foreshadowing_items]
        user_parts.append(f"【待回收伏笔】\n" + "\n".join(fs_lines))

    user_parts.append(f"\n【章节正文】\n{chapter_content}")

    user_parts.append(
        "\n\n请输出JSON格式评审结果，结构如下：\n"
        '{"overall_score": 8.5, "overall_comment": "...", '
        '"dimensions": [{"name": "文笔质量", "score": 8, "comment": "..."}, ...], '
        '"annotations": [{"paragraph_index": 0, "quote": "...", "issue": "...", "suggestion": "..."}, ...]}'
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_summary_prompt(chapter_content="", novel_title="", db=None):
    system_prompt = _load_system_prompt(db, "summary", (
        "你是一位专业的小说编辑，擅长对小说章节进行精炼的摘要总结。"
        "请用200字以内概括章节的核心情节和重要事件。"
    ))
    user_parts = []
    if novel_title:
        user_parts.append(f"小说：{novel_title}")
    user_parts.append(f"章节正文：\n{chapter_content}")
    user_parts.append("\n请用200字以内输出本章摘要。")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_rewrite_prompt(original_content="", critic_feedback="", novel_title="",
                         chapter_title="", outline="", user_directive="", db=None):
    system_prompt = _load_system_prompt(db, "rewrite", (
        "你是一位专业的小说作家。根据评审意见修改你的作品，"
        "解决指出的问题，同时保持原文的优点。"
    ))

    # 注入去AI化约束（最高优先级）
    full_system = DEFAULT_WRITER_CONSTRAINTS + """

【改写特别注意】
- 不要"修复"文本中的自然不完美（碎片句、口语化表达、不工整的节奏）
- 这些是有意为之的风格特征，不是错误
- 只修复评审指出的具体问题，不要"美化"文字
- 保持原文的人味，不要改得更"流畅优美"
""" + "\n\n" + system_prompt

    blocks = []
    if novel_title:
        blocks.append(_section("小说名称", novel_title))
    if chapter_title:
        blocks.append(_section("章节标题", chapter_title))
    if outline:
        blocks.append(_section("本章大纲", outline))
    if user_directive:
        blocks.append(_section("特别指示", user_directive))
    blocks.append(_section("评审意见（务必修改）", critic_feedback))
    blocks.append(_section("原文", original_content))
    blocks.append("\n请根据评审意见输出修改后的完整章节正文。")

    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": "\n\n".join(b for b in blocks if b)},
    ]
