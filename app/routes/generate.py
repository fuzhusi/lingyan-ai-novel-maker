import json
import time
from flask import Blueprint, request, Response, jsonify, stream_with_context
from app.services.prompt_builder import (
    build_outline_prompt, build_writer_prompt, assemble_chapter_context,
)
from app.services.prompt_builder.context import get_excitement_recent
from app.services.writer_chain import (
    build_writer_kwargs, build_scene_plan, generation_tokens,
    CHAPTER_WORD_TARGET,
)
from app.services.llm import LLMError
from app.models import db, Novel, Character, Chapter
from app.config_utils import get_effective_config, get_model_config

generate_bp = Blueprint("generate", __name__, url_prefix="/api")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_to_sse(messages, cfg, word_target=None, phase="write",
                   scene_plan=None, injection_report=None):
    """Shared streaming helper — yields SSE event strings.

    word_target: 传入时启用字数保障——流结束后正文不足字数底线
    则携带前文尾部自动续写，续写 token 继续推入同一 SSE 流。
    scene_plan: 节拍级生成计划（大纲含 ≥2 拍时逐拍生成，见 writer_chain）。
    生成逻辑（含节拍轮/续写轮）在 writer_chain.generation_tokens，
    与编排器共用。

    进度帧（{"status": {...}}）：阶段/轮次/首字延迟/耗时等诊断信息穿插在
    token 帧之间。旧前端只认 token/error/done 字段，未知帧自动忽略，
    故对既有客户端完全向后兼容。
    """
    collected = []
    pending = []
    started = time.time()

    def on_event(ev):
        # 事件在生成器内部同步触发，先攒后冲即可保序，无需加锁
        pending.append(ev)

    try:
        yield _sse_event({"status": {
            "stage": "stream_start", "phase": phase,
            "model": cfg.get("model_name", ""),
            "provider": cfg.get("provider_type", ""),
        }})
        if injection_report and injection_report.get("dims"):
            yield _sse_event({"status": {
                "stage": "injection_report",
                "dims": injection_report["dims"],
                "total_chars": injection_report.get("total_chars", 0),
                "degraded": injection_report.get("degraded", []),
            }})
        for token in generation_tokens(messages, cfg, word_target=word_target,
                                       on_event=on_event, scene_plan=scene_plan):
            while pending:
                yield _sse_event({"status": pending.pop(0)})
            collected.append(token)
            yield _sse_event({"token": token})
        while pending:
            yield _sse_event({"status": pending.pop(0)})
        yield _sse_event({"done": True, "full_text": "".join(collected),
                          "elapsed_s": round(time.time() - started, 1)})
    except LLMError as e:
        # 栈展开时 finally 里追加的收尾帧（round_end 等）一并冲刷，不丢进度上下文
        while pending:
            yield _sse_event({"status": pending.pop(0)})
        yield _sse_event({"error": str(e), "full_text": "".join(collected)})
    except Exception as e:
        while pending:
            yield _sse_event({"status": pending.pop(0)})
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
    # None/缺省 = 全部角色（兼容旧流程与 MCP）；显式空串 = 不注入任何角色档案；
    # 非法值按显式选择失败处理（[]），绝不静默放大为"全部角色"
    character_ids = None
    raw_ids = request.form.get("character_ids")
    if raw_ids is not None and raw_ids.strip():
        try:
            character_ids = [int(x) for x in raw_ids.split(",") if x.strip()]
        except ValueError:
            character_ids = []
    elif raw_ids is not None:
        character_ids = []

    # 细纲硬门禁（戏剧字段，旧格式软通过）：请求未带大纲时回落到章节已存大纲
    from app.services.outline_drama import (
        write_ready_outline, outline_gate_error, upgrade_freeform_outline)
    if not (outline or "").strip() and novel_id and chapter_number:
        ch = (Chapter.query
              .filter_by(novel_id=novel_id, chapter_number=chapter_number)
              .first())
        if ch and (ch.outline or "").strip():
            outline = ch.outline.strip()
    ready = write_ready_outline(outline)
    if not ready["ok"]:
        # 自动升级路径：旧格式自由文本大纲 → 一次 LLM 调用改写成 7 字段。
        # 成功则改写稿落库并继续生成；失败才返回 400 与补全引导。
        novel_for_upgrade = (Novel.query.get(novel_id)
                             if novel_id else None)
        try:
            cfg_u = (get_effective_config(novel_for_upgrade, agent_type="outline")
                     if novel_for_upgrade else get_model_config(agent_type="outline"))
            cfg_u["genre"] = novel_for_upgrade.genre if novel_for_upgrade else ""
            upgraded = upgrade_freeform_outline(outline, cfg_u)
        except Exception:
            upgraded = None
        if upgraded:
            ready2 = write_ready_outline(upgraded)
            if ready2["ok"]:
                outline = upgraded
                if novel_id and chapter_number:
                    ch = (Chapter.query
                          .filter_by(novel_id=novel_id,
                                     chapter_number=chapter_number)
                          .first())
                    if ch:
                        ch.outline = upgraded
                        db.session.commit()
                ready = ready2
    if not ready["ok"]:
        return jsonify({
            "error": outline_gate_error(outline),
            "hint": "点击「重新生成大纲」可自动按固定格式重写后再生成正文",
            "drama": {"blocking": ready["blocking"], "warnings": ready["warnings"],
                      "has": ready["has"]},
        }), 400
    outline = ready.get("effective_outline") or outline

    # 写作包：上下文组装/预算压缩/锚例/罗盘/tone 指令/备忘录统一在 writer_chain
    kw, novel = build_writer_kwargs(novel_id, chapter_number, outline,
                                    user_directive=user_directive,
                                    character_ids=character_ids)

    injection_report = kw.pop("injection_report", None)
    messages = build_writer_prompt(
        novel_title=novel_title,
        chapter_title=chapter_title,
        outline=outline,
        user_directive=user_directive,
        db=db,
        chapter_number=chapter_number,
        **kw,
    )

    cfg = get_effective_config(novel, agent_type="writer")
    # 节拍级生成计划（大纲含 ≥2 拍时逐拍写；None 则整章路径，行为不变）
    scene_plan = build_scene_plan(outline, kw=kw, word_target=CHAPTER_WORD_TARGET,
                                  novel_id=novel_id, chapter_number=chapter_number)
    if scene_plan is not None:
        scene_plan["prev_ending"] = kw.get("prev_ending", "")
    return Response(stream_with_context(
        _stream_to_sse(messages, cfg, word_target=CHAPTER_WORD_TARGET,
                       phase="write", scene_plan=scene_plan,
                       injection_report=injection_report)),
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
            "world_settings": ctx["world_settings"],
            "excitement_recent": get_excitement_recent(novel_id),
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
    return Response(stream_with_context(_stream_to_sse(messages, cfg, phase="outline")),
                    mimetype="text/event-stream")


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
        blocks.append("【聚焦角色设定】\n" + "\n".join(char_parts))

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
            blocks.append("【前情提要】\n" + "\n".join(summaries))
        target_ch = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
        if target_ch and target_ch.outline:
            blocks.append(f"【本章大纲】\n{target_ch.outline}")

    blocks.append("\n请直接输出聚焦于该角色的小说片段。")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]

    cfg = get_effective_config(novel, agent_type="writer")
    return Response(stream_with_context(_stream_to_sse(messages, cfg, phase="focus")),
                    mimetype="text/event-stream")


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
