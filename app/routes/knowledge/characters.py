"""角色管理路由：模板、CRUD、AI 生成。"""
import json as _json
from flask import render_template, request, redirect, url_for, jsonify
from app.models import (db, Novel, Character, Chapter, ChapterVersion)
from app.routes.knowledge import knowledge_bp


# ---------------------------------------------------------------------------
# 角色模板库
# ---------------------------------------------------------------------------

CHARACTER_TEMPLATES = {
    "brave_hero": {
        "name": "热血少年",
        "personality": "勇敢热血，正义感强，重情重义",
        "speaking_style": "直率豪爽，不拘小节",
        "appearance": "身材健壮，目光坚定，常带武器",
        "background": "出身平凡，因某个契机踏上冒险之旅",
        "motivation": "保护重要的人，追求正义",
        "arc_direction": "从莽撞冲动到成熟稳重",
    },
    "cold_swordsman": {
        "name": "冷峻剑客",
        "personality": "冷静沉默，孤傲寡言，内心炽热",
        "speaking_style": "言简意赅，字字珠玑",
        "appearance": "黑发剑眉，身着劲装，腰悬长剑",
        "background": "身世神秘，背负血海深仇",
        "motivation": "追寻真相，报仇雪恨",
        "arc_direction": "从孤僻到信任他人，从复仇到守护",
    },
    "gentle_lady": {
        "name": "温婉少女",
        "personality": "温柔善良，聪慧坚韧，内心坚强",
        "speaking_style": "轻柔委婉，善解人意",
        "appearance": "青丝如瀑，明眸皓齿，温婉大方",
        "background": "大家闺秀或书香门第，自幼聪慧",
        "motivation": "守护家人，追寻理想",
        "arc_direction": "从柔弱到坚强，承担责任",
    },
    "scheming_villain": {
        "name": "腹黑反派",
        "personality": "心思缜密，城府极深，外柔内刚",
        "speaking_style": "温和有礼，绵里藏针",
        "appearance": "俊美或端庄，常带微笑",
        "background": "出身名门或隐藏极深",
        "motivation": "夺取权力，复仇或野心",
        "arc_direction": "从伪装到暴露，从对抗到覆灭",
    },
    "wise_mentor": {
        "name": "智慧长者",
        "personality": "睿智慈祥，看透世事，因材施教",
        "speaking_style": "富含哲理，循循善诱",
        "appearance": "白发苍苍，目光深邃，气度不凡",
        "background": "曾经叱咤风云，如今退隐江湖",
        "motivation": "传承薪火，守护正道",
        "arc_direction": "从引导到牺牲，从传授到放手",
    },
    "comic_relief": {
        "name": "搞笑担当",
        "personality": "活泼贪玩，嘴贫心善，运气爆棚",
        "speaking_style": "贫嘴滑舌，金句频出",
        "appearance": "机灵古怪，嬉皮笑脸",
        "background": "出身市井或神秘身世",
        "motivation": "追求快乐，保护朋友",
        "arc_direction": "从玩世不恭到承担责任",
    },
}


def apply_template(template_key, name_override=""):
    """获取角色模板数据。"""
    template = CHARACTER_TEMPLATES.get(template_key, {}).copy()
    if name_override:
        template["name"] = name_override
    return template


@knowledge_bp.route("/characters/templates")
def character_templates(novel_id):
    """获取所有角色模板（JSON）。"""
    return jsonify(CHARACTER_TEMPLATES)


@knowledge_bp.route("/characters/create-from-template", methods=["POST"])
def create_character_from_template(novel_id):
    """从模板创建角色。"""
    template_key = request.form.get("template_key", "")
    name_override = request.form.get("name", "").strip()
    data = apply_template(template_key, name_override)

    char = Character(
        novel_id=novel_id,
        name=data.get("name", ""),
        personality=data.get("personality", ""),
        speaking_style=data.get("speaking_style", ""),
        appearance=data.get("appearance", ""),
        background=data.get("background", ""),
        motivation=data.get("motivation", ""),
        arc_direction=data.get("arc_direction", ""),
    )
    db.session.add(char)
    db.session.commit()
    return redirect(url_for("knowledge.characters_page", novel_id=novel_id))


@knowledge_bp.route("/characters/ai-generate", methods=["POST"])
def ai_generate_character(novel_id):
    """AI 自动生成角色（流式）。"""
    from app.config_utils import get_effective_config
    from app.services.llm import call_llm_sync, stream_llm_tokens, LLMError

    novel = Novel.query.get_or_404(novel_id)
    role_hint = request.form.get("role_hint", "")
    style_hint = request.form.get("style_hint", "")

    existing = Character.query.filter_by(novel_id=novel_id).all()
    existing_names = [c.name for c in existing]

    system = (
        "你是一位专业的小说人物设定专家。根据小说信息和用户提示，"
        "生成一个完整的角色设定。输出严格的JSON格式，不要输出其他内容。"
    )
    user = (
        f"小说类型：{novel.genre or '未设置'}\n"
        f"小说简介：{novel.synopsis or '无'}\n"
        f"世界观：{(novel.world_intro or '')[:500]}\n"
        f"已存在角色：{', '.join(existing_names) if existing_names else '无'}\n"
        f"用户提示：{role_hint or '无'}\n"
        f"风格要求：{style_hint or '符合小说整体风格'}\n\n"
        "请生成一个角色，输出以下JSON结构：\n"
        '{"name": "角色名", '
        '"personality": "性格特点（50字内）", '
        '"speaking_style": "说话风格（30字内）", '
        '"appearance": "外貌描写（50字内）", '
        '"background": "背景故事（80字内）", '
        '"motivation": "核心动机（30字内）", '
        '"arc_direction": "角色弧光（30字内）"}\n\n'
        "JSON："
    )

    try:
        cfg = get_effective_config(novel, agent_type="writer")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = call_llm_sync(
            cfg.get("model_name"),
            messages,
            cfg.get("api_key"),
            cfg.get("base_url"),
            cfg.get("provider_type", "deepseek"),
            cfg.get("temperature"),
            cfg.get("max_tokens"),
        )
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True; continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        data = _json.loads(text)
    except LLMError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "character": data})


# ---------------------------------------------------------------------------
# 角色 CRUD
# ---------------------------------------------------------------------------

@knowledge_bp.route("/characters")
def characters_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    characters = Character.query.filter_by(novel_id=novel_id).order_by(Character.name).all()
    return render_template("characters.html", novel=novel, characters=characters)


@knowledge_bp.route("/characters/create", methods=["POST"])
def create_character(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    char = Character(
        novel_id=novel_id,
        name=request.form.get("name", "").strip(),
        personality=request.form.get("personality", ""),
        speaking_style=request.form.get("speaking_style", ""),
        appearance=request.form.get("appearance", ""),
        background=request.form.get("background", ""),
        motivation=request.form.get("motivation", ""),
        arc_direction=request.form.get("arc_direction", ""),
    )
    db.session.add(char)
    db.session.commit()
    return redirect(url_for("knowledge.characters_page", novel_id=novel_id))


@knowledge_bp.route("/characters/<int:char_id>/edit", methods=["POST"])
def edit_character(novel_id, char_id):
    char = Character.query.get_or_404(char_id)
    for field in ["name", "personality", "speaking_style", "appearance",
                  "background", "motivation", "arc_direction", "status_json"]:
        val = request.form.get(field, "")
        if val:
            setattr(char, field, val)
    db.session.commit()
    return redirect(url_for("knowledge.characters_page", novel_id=novel_id))


@knowledge_bp.route("/characters/<int:char_id>/delete", methods=["POST"])
def delete_character(novel_id, char_id):
    char = Character.query.get_or_404(char_id)
    db.session.delete(char)
    db.session.commit()
    return redirect(url_for("knowledge.characters_page", novel_id=novel_id))


@knowledge_bp.route("/characters/<int:char_id>/detail")
def character_detail(novel_id, char_id):
    novel = Novel.query.get_or_404(novel_id)
    character = Character.query.get_or_404(char_id)

    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()
    chapter_mentions = []
    for ch in chapters:
        mentions = []
        if ch.outline and character.name in ch.outline:
            mentions.append("大纲")
        versions = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(ChapterVersion.version_number.desc()).all()
        for v in versions:
            if character.name in v.content:
                mentions.append(f"V{v.version_number}")
                break
        if mentions:
            chapter_mentions.append({"chapter": ch, "mentions": mentions})

    return render_template("character_detail.html", novel=novel, character=character,
                           chapter_mentions=chapter_mentions)
