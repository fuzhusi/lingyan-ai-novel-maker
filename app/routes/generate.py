import json
from flask import Blueprint, request, Response, jsonify, current_app
from app.services.prompt_builder import (
    build_outline_prompt, build_writer_prompt, assemble_chapter_context,
)
from app.services.writer_chain import (
    build_writer_kwargs, generation_tokens,
    CHAPTER_WORD_TARGET,
)
from app.services.llm import LLMError
from app.models import db, Novel, Character, Chapter
from app.config_utils import get_effective_config

generate_bp = Blueprint("generate", __name__, url_prefix="/api")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_to_sse(messages, cfg, word_target=None):
    """Shared streaming helper — yields SSE event strings.

    word_target: 传入时启用字数保障——流结束后正文不足字数底线
    则携带前文尾部自动续写，续写 token 继续推入同一 SSE 流。
    生成逻辑（含续写轮）在 writer_chain.generation_tokens，与编排器共用。
    """
    collected = []
    try:
        for token in generation_tokens(messages, cfg, word_target=word_target):
            collected.append(token)
            yield _sse_event({"token": token})
        yield _sse_event({"done": True, "full_text": "".join(collected)})
    except LLMError as e:
        yield _sse_event({"error": str(e), "full_text": "".join(collected)})
    except Exception as e:
        yield _sse_event({"error": str(e), "full_text": "".join(collected)})


@generate_bp.route("/generate-stream", methods=["POST"])
def generate_stream():
    outline = request.form.get("outline", "")
    user_directive = request.form.get("user_directive", "")
    chapter_title = request.form.get("chapter_title", "")
    novel_title = request.form.get("novel_title", "")
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)

    # 出场角色勾选（前端角色库勾选区）：逗号分隔的角色 id
    # None/缺省 = 全部角色（兼容旧流程与 MCP）；显式空串 = 不注入任何角色档案
    character_ids = None
    raw_ids = request.form.get("character_ids")
    if raw_ids is not None and raw_ids.strip():
        try:
            character_ids = [int(x) for x in raw_ids.split(",") if x.strip()]
        except ValueError:
            character_ids = None
    elif raw_ids is not None:
        character_ids = []

    # 写作包：上下文组装/预算压缩/锚例/罗盘/tone 指令/备忘录统一在 writer_chain
    kw, novel = build_writer_kwargs(novel_id, chapter_number, outline,
                                    user_directive=user_directive,
                                    character_ids=character_ids)

    messages = build_writer_prompt(
        novel_title=novel_title,
        chapter_title=chapter_title,
        outline=outline,
        user_directive=user_directive,
        db=db,
        **kw,
    )

    cfg = get_effective_config(novel, agent_type="writer")
    return Response(_stream_to_sse(messages, cfg, word_target=CHAPTER_WORD_TARGET),
                    mimetype="text/event-stream")


@generate_bp.route("/outline-stream", methods=["POST"])
def outline_stream():
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    novel_title = request.form.get("novel_title", "")
    chapter_title = request.form.get("chapter_title", "")
    genre = request.form.get("genre", "")
    synopsis = request.form.get("synopsis", "")
    world_intro = request.form.get("world_intro", "")

    kw = {}
    if novel_id and chapter_number:
        ctx = assemble_chapter_context(novel_id, chapter_number, db)
        kw = {
            "characters": ctx["characters"],
            "summaries": ctx["summaries"],
            "foreshadowing_items": ctx["foreshadowing_items"],
            "author_intent": ctx["author_intent"],
            "current_focus": ctx["current_focus"],
        }

    messages = build_outline_prompt(
        novel_title=novel_title,
        genre=genre,
        synopsis=synopsis,
        world_intro=world_intro,
        chapter_title=chapter_title,
        chapter_number=chapter_number or 1,
        db=db,
        **kw,
    )

    novel = Novel.query.get(novel_id) if novel_id else None
    cfg = get_effective_config(novel, agent_type="outline")
    return Response(_stream_to_sse(messages, cfg), mimetype="text/event-stream")


@generate_bp.route("/focus-generate-stream", methods=["POST"])
def focus_generate_stream():
    novel_id = request.form.get("novel_id", type=int)
    char_name = request.form.get("char_name", "")
    scene = request.form.get("scene", "")
    tone = request.form.get("tone", "")
    chapter_number = request.form.get("chapter_number", type=int)

    novel = Novel.query.get_or_404(novel_id)
    character = Character.query.filter_by(novel_id=novel_id, name=char_name).first()

    system_prompt = (
        f"你是一位专业的小说作家。现在请以角色「{char_name}」为核心，"
        f"根据以下场景和角色设定，写出一段聚焦于该角色的小说片段。"
        f"要深入展现该角色的内心世界、性格特征和行为方式。"
    )
    # 创作罗盘（与其他三条链路共用同一拼装 helper，防止文案漂移）
    try:
        from app.services.prompt_builder.context import build_compass_block
        compass = build_compass_block(novel.author_intent, novel.current_focus)
        if compass:
            system_prompt += "\n\n" + compass
    except Exception:
        pass
    try:
        from app.services.style_fingerprint import format_anchor_for_prompt
        anchor_ctx = format_anchor_for_prompt()
        if anchor_ctx:
            system_prompt += "\n\n" + anchor_ctx
    except Exception:
        pass

    blocks = []
    blocks.append(f"【小说名称】\n{novel.title}")
    if novel.synopsis:
        blocks.append(f"【小说简介】\n{novel.synopsis}")

    if character:
        char_parts = [f"姓名：{character.name}"]
        if character.personality:
            char_parts.append(f"性格：{character.personality}")
        if character.speaking_style:
            char_parts.append(f"说话风格：{character.speaking_style}")
        if character.appearance:
            char_parts.append(f"外貌：{character.appearance}")
        if character.background:
            char_parts.append(f"背景：{character.background}")
        if character.motivation:
            char_parts.append(f"动机：{character.motivation}")
        if character.arc_direction:
            char_parts.append(f"角色弧光：{character.arc_direction}")
        blocks.append(f"【聚焦角色设定】\n" + "\n".join(char_parts))

    blocks.append(f"【写作场景】\n{scene}")
    if tone:
        blocks.append(f"【情感基调】\n{tone}")

    if chapter_number:
        from app.models import ChapterSummary
        prev_chapters = (Chapter.query
                         .filter_by(novel_id=novel_id)
                         .filter(Chapter.chapter_number < chapter_number)
                         .order_by(Chapter.chapter_number).all())
        summaries = []
        for ch in prev_chapters:
            cs = ChapterSummary.query.filter_by(chapter_id=ch.id).first()
            if cs:
                summaries.append(f"第{ch.chapter_number}章：{cs.summary}")
        if summaries:
            blocks.append(f"【前情提要】\n" + "\n".join(summaries))
        target_ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if target_ch and target_ch.outline:
            blocks.append(f"【本章大纲】\n{target_ch.outline}")

    blocks.append("\n请直接输出聚焦于该角色的小说片段。")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]

    cfg = get_effective_config(novel, agent_type="writer")
    return Response(_stream_to_sse(messages, cfg), mimetype="text/event-stream")


@generate_bp.route("/chapter-pipeline", methods=["POST"])
def chapter_pipeline():
    """一键本章流水线（P3）：缺大纲生成 → 正文 → 门禁 → 收敛（回滚兜底）→ 人工闸门。

    同步长请求（整章生成，数十秒级）。Body JSON:
    {"novel_id", "chapter_number", "user_directive"?, "auto_save"?}
    auto_save=True 时落 AI 版本（仍不自动审批）。
    """
    data = request.get_json(silent=True) or {}
    novel_id = data.get("novel_id") or request.form.get("novel_id", type=int)
    chapter_number = (data.get("chapter_number")
                      or request.form.get("chapter_number", type=int))
    if not novel_id or not chapter_number:
        return jsonify({"error": "novel_id / chapter_number required"}), 400
    from app.services.chapter_runner import run_chapter_pipeline
    result = run_chapter_pipeline(
        novel_id, chapter_number,
        user_directive=data.get("user_directive")
        or request.form.get("user_directive", ""),
        auto_save=bool(data.get("auto_save")),
    )
    return jsonify(result)
