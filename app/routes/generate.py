import json
from flask import Blueprint, request, Response, current_app
from app.services.prompt_builder import (
    build_writer_prompt, assemble_chapter_context, build_outline_prompt
)
from app.services.llm import stream_llm_tokens, LLMError
from app.models import db, Novel, Character, Chapter
from app.config_utils import get_effective_config

generate_bp = Blueprint("generate", __name__, url_prefix="/api")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_to_sse(messages, cfg):
    """Shared streaming helper — yields SSE event strings."""
    collected = []
    try:
        for token in stream_llm_tokens(
            model=cfg["model_name"],
            messages=messages,
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.8),
            max_tokens=cfg.get("max_tokens", 4096),
        ):
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

    kw = {}
    if novel_id and chapter_number:
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

        ctx = assemble_chapter_context(novel_id, chapter_number, db, character_ids=character_ids)
        kw = {
            "characters": ctx["characters"],
            "world_settings": ctx["world_settings"],
            "summaries": ctx["summaries"],
            "earlier_summaries": ctx["earlier_summaries"],
            "prev_ending": ctx["prev_ending"],
            "foreshadowing_items": ctx["foreshadowing_items"],
            "synopsis": ctx["synopsis"],
            "world_intro": ctx["world_intro"],
            "outline_node_context": ctx["outline_node_context"],
        }

        # Causal chain context from previous chapters
        try:
            from app.services.causal_chain import get_chain_context, format_chain_for_prompt
            chains = get_chain_context(novel_id, chapter_number)
            kw["causal_chain"] = format_chain_for_prompt(chains)
        except Exception:
            pass

        # Vector memory context
        try:
            from app.services.vector_memory import build_context_for_chapter
            kw["memory_context"] = build_context_for_chapter(novel_id, chapter_number, outline)
        except Exception:
            pass

        # Information boundary context
        try:
            from app.services.info_boundary import format_knowledge_boundaries
            boundary_ctx = format_knowledge_boundaries(novel_id, chapter_number)
            if boundary_ctx:
                existing = kw.get("memory_context", "")
                kw["memory_context"] = (existing + "\n\n" + boundary_ctx).strip()
        except Exception:
            pass

        # Temporal truth context
        try:
            from app.services.temporal_truth import format_truths_for_prompt
            truth_ctx = format_truths_for_prompt(novel_id, chapter_number)
            if truth_ctx:
                existing = kw.get("memory_context", "")
                kw["memory_context"] = (existing + "\n\n" + truth_ctx).strip()
        except Exception:
            pass

        # Style fingerprint
        try:
            from app.services.style_fingerprint import load_style, format_style_for_prompt
            style = load_style()
            if style:
                style_ctx = format_style_for_prompt(style)
                if style_ctx:
                    existing = kw.get("memory_context", "")
                    kw["memory_context"] = (existing + "\n\n" + style_ctx).strip()
        except Exception:
            pass

        # Active skills — 已移至 writer.py 的 system message 中注入
        # 不再在 memory_context 中注入技能提示

    messages = build_writer_prompt(
        novel_title=novel_title,
        chapter_title=chapter_title,
        outline=outline,
        user_directive=user_directive,
        db=db,
        **kw,
    )

    novel = Novel.query.get(novel_id) if novel_id else None
    cfg = get_effective_config(novel, agent_type="writer")
    return Response(_stream_to_sse(messages, cfg), mimetype="text/event-stream")


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
