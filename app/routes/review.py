import json
import difflib
from flask import Blueprint, request, Response, jsonify, current_app
from app.models import (db, ChapterVersion, CriticReview, ChapterSummary, ChapterMemory,
                        Foreshadowing, Novel, Character)
from app.services.prompt_builder import (build_critic_prompt, build_summary_prompt,
                                          build_rewrite_prompt, assemble_chapter_context)
from app.services.llm import stream_llm_tokens, call_llm_sync, LLMError
from app.config_utils import get_effective_config


review_bp = Blueprint("review", __name__, url_prefix="/api")


def _build_memory_prompt(chapter_content="", chapter_number=0, novel_title="", characters=None):
    """Build prompt for structured chapter memory generation."""
    char_names = ", ".join(c.name for c in characters) if characters else ""

    system_prompt = (
        "你是一位小说分析专家。请分析章节内容，提取结构化记忆信息。"
        "输出严格的JSON格式，不要输出其他内容。"
    )
    user_prompt = (
        f"小说：{novel_title}\n"
        f"第{chapter_number}章\n"
        f"已知角色：{char_names}\n\n"
        f"章节正文：\n{chapter_content}\n\n"
        "请提取以下信息并输出JSON：\n"
        '{"summary": "200字以内章节摘要", '
        '"key_events": ["事件1", "事件2", ...], '
        '"character_changes": {"角色名": "变化描述", ...}, '
        '"foreshadow_events": [{"description": "伏笔相关事件", "foreshadow_id": null}], '
        '"new_characters": ["新出场角色名", ...], '
        '"scenes": [{"setting": "场景地点", "characters": ["角色1"], "summary": "50字场景摘要"}, ...]}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_chat(messages, cfg):
    collected = []
    try:
        for token in stream_llm_tokens(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.5), max_tokens=cfg.get("max_tokens", 4096),
        ):
            collected.append(token)
            yield None, token
        yield "".join(collected), None
    except LLMError as e:
        yield None, _sse_event({"error": str(e)})
    except Exception as e:
        yield None, _sse_event({"error": str(e)})


@review_bp.route("/review-stream", methods=["POST"])
def review_stream():
    version_id = request.form.get("version_id", type=int)
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    novel_title = request.form.get("novel_title", "")

    version = ChapterVersion.query.get_or_404(version_id)
    chapter = version.chapter

    kw = {}
    if novel_id and chapter_number:
        ctx = assemble_chapter_context(novel_id, chapter_number, db)
        kw = {
            "characters": ctx["characters"],
            "world_settings": ctx["world_settings"],
            "foreshadowing_items": ctx["foreshadowing_items"],
        }

    messages = build_critic_prompt(
        novel_title=novel_title,
        chapter_title=chapter.title,
        chapter_content=version.content,
        outline=chapter.outline,
        user_directive=chapter.user_directive,
        db=db,
        **kw,
    )

    novel = Novel.query.get(novel_id) if novel_id else None
    cfg = get_effective_config(novel, agent_type="critic")

    def generate():
        full_text, last_chunk = None, None
        for full_text, token in _stream_chat(messages, cfg):
            if token:
                yield _sse_event({"token": token})
            elif full_text is not None:
                yield _sse_event({"done": True, "full_text": full_text})
                return
        if full_text is None:
            yield _sse_event({"error": "no response", "full_text": ""})

    return Response(generate(), mimetype="text/event-stream")


@review_bp.route("/review/save", methods=["POST"])
def save_review():
    version_id = request.form.get("version_id", type=int)
    full_response = request.form.get("full_response", "")
    version = ChapterVersion.query.get_or_404(version_id)

    overall_score = None
    dimensions = []
    annotations = []
    overall_comment = ""

    try:
        data = json.loads(full_response)
        overall_score = data.get("overall_score")
        overall_comment = data.get("overall_comment", "")
        dimensions = data.get("dimensions", [])
        annotations = data.get("annotations", [])
    except json.JSONDecodeError:
        overall_comment = full_response

    review = CriticReview(
        version_id=version_id,
        overall_score=overall_score,
        dimension_scores_json=json.dumps(dimensions, ensure_ascii=False),
        annotations_json=json.dumps(annotations, ensure_ascii=False),
        overall_comment=overall_comment,
        full_response=full_response,
    )
    db.session.add(review)
    db.session.commit()

    return jsonify({
        "id": review.id,
        "overall_score": overall_score,
        "dimensions": dimensions,
        "annotations": annotations,
        "overall_comment": overall_comment,
    })


@review_bp.route("/review/get")
def get_review():
    version_id = request.args.get("version_id", type=int)
    if not version_id:
        return jsonify({"error": "missing version_id"}), 400
    review = (CriticReview.query
              .filter_by(version_id=version_id)
              .order_by(CriticReview.id.desc()).first())
    if not review:
        return jsonify(None)
    return jsonify({
        "id": review.id,
        "overall_score": review.overall_score,
        "dimensions": json.loads(review.dimension_scores_json or "[]"),
        "annotations": json.loads(review.annotations_json or "[]"),
        "overall_comment": review.overall_comment,
        "user_feedback": review.user_feedback or "",
    })


@review_bp.route("/review/feedback", methods=["POST"])
def save_feedback():
    review_id = request.form.get("review_id", type=int)
    feedback = request.form.get("feedback", "")
    review = CriticReview.query.get_or_404(review_id)
    review.user_feedback = feedback
    db.session.commit()
    return jsonify({"ok": True})


@review_bp.route("/approve", methods=["POST"])
def approve_version():
    version_id = request.form.get("version_id", type=int)
    version = ChapterVersion.query.get_or_404(version_id)
    version.approved = True

    # Generate chapter summary automatically
    chapter = version.chapter
    try:
        cfg = get_effective_config(chapter.novel, agent_type="summary")
        messages = build_summary_prompt(
            chapter_content=version.content,
            novel_title=chapter.novel.title,
            db=db,
        )
        summary_text = call_llm_sync(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.5), max_tokens=cfg.get("max_tokens", 1024),
        )
    except LLMError:
        summary_text = ""
    except Exception:
        summary_text = ""

    if summary_text:
        cs = ChapterSummary.query.filter_by(chapter_id=chapter.id).first()
        if cs:
            cs.summary = summary_text
        else:
            cs = ChapterSummary(chapter_id=chapter.id, summary=summary_text)
            db.session.add(cs)

    # Generate structured chapter memory
    try:
        memory_cfg = get_effective_config(chapter.novel, agent_type="memory")
        memory_prompt = _build_memory_prompt(
            chapter_content=version.content,
            chapter_number=chapter.chapter_number,
            novel_title=chapter.novel.title,
            characters=Character.query.filter_by(novel_id=chapter.novel_id).all(),
        )
        memory_text = call_llm_sync(
            model=memory_cfg["model_name"], messages=memory_prompt,
            api_key=memory_cfg.get("api_key", ""), base_url=memory_cfg.get("base_url", ""),
            provider_type=memory_cfg.get("provider_type", "deepseek"),
            temperature=memory_cfg.get("temperature", 0.5), max_tokens=memory_cfg.get("max_tokens", 1024),
        )
        memory_data = json.loads(memory_text) if memory_text else {}
    except LLMError:
        memory_data = {}
    except Exception:
        memory_data = {}

    if memory_data:
        cm = ChapterMemory.query.filter_by(chapter_id=chapter.id).first()
        if cm:
            cm.summary = memory_data.get("summary", summary_text)
            cm.key_events_json = json.dumps(memory_data.get("key_events", []), ensure_ascii=False)
            cm.character_changes_json = json.dumps(memory_data.get("character_changes", {}), ensure_ascii=False)
            cm.foreshadow_events_json = json.dumps(memory_data.get("foreshadow_events", []), ensure_ascii=False)
            cm.new_characters_json = json.dumps(memory_data.get("new_characters", []), ensure_ascii=False)
            cm.scenes_json = json.dumps(memory_data.get("scenes", []), ensure_ascii=False)
        else:
            cm = ChapterMemory(
                novel_id=chapter.novel_id,
                chapter_id=chapter.id,
                chapter_number=chapter.chapter_number,
                summary=memory_data.get("summary", summary_text),
                key_events_json=json.dumps(memory_data.get("key_events", []), ensure_ascii=False),
                character_changes_json=json.dumps(memory_data.get("character_changes", {}), ensure_ascii=False),
                foreshadow_events_json=json.dumps(memory_data.get("foreshadow_events", []), ensure_ascii=False),
                new_characters_json=json.dumps(memory_data.get("new_characters", []), ensure_ascii=False),
                scenes_json=json.dumps(memory_data.get("scenes", []), ensure_ascii=False),
            )
            db.session.add(cm)

    # Update story state chapter counter
    from app.models import StoryState
    story_state = StoryState.query.filter_by(novel_id=chapter.novel_id).first()
    if story_state:
        story_state.current_chapter = max(story_state.current_chapter or 0, chapter.chapter_number)

    db.session.commit()
    return jsonify({"approved": True, "summary": summary_text})


@review_bp.route("/diff")
def version_diff():
    vid1 = request.args.get("v1", type=int)
    vid2 = request.args.get("v2", type=int)
    if not vid1 or not vid2:
        return jsonify({"error": "need v1 and v2"}), 400

    v1 = ChapterVersion.query.get_or_404(vid1)
    v2 = ChapterVersion.query.get_or_404(vid2)

    diff_lines = list(difflib.unified_diff(
        v1.content.splitlines(keepends=True),
        v2.content.splitlines(keepends=True),
        fromfile=f"V{v1.version_number} ({v1.source})",
        tofile=f"V{v2.version_number} ({v2.source})",
    ))

    return jsonify({
        "v1": {"version_number": v1.version_number, "source": v1.source},
        "v2": {"version_number": v2.version_number, "source": v2.source},
        "diff": "".join(diff_lines),
    })


@review_bp.route("/rewrite-stream", methods=["POST"])
def rewrite_stream():
    version_id = request.form.get("version_id", type=int)
    novel_title = request.form.get("novel_title", "")

    version = ChapterVersion.query.get_or_404(version_id)
    chapter = version.chapter

    # Get latest critic feedback (and user feedback if present)
    review = (CriticReview.query
              .filter_by(version_id=version_id)
              .order_by(CriticReview.id.desc()).first())
    critic_feedback = review.overall_comment if review else "请改进本章内容"
    if review and review.user_feedback and review.user_feedback.strip():
        critic_feedback += "\n\n【用户补充意见】\n" + review.user_feedback.strip()

    messages = build_rewrite_prompt(
        original_content=version.content,
        critic_feedback=critic_feedback,
        novel_title=novel_title,
        chapter_title=chapter.title,
        outline=chapter.outline,
        user_directive=chapter.user_directive,
        db=db,
    )

    cfg = get_effective_config(chapter.novel, agent_type="rewrite")

    def generate():
        full_text, last_chunk = None, None
        for full_text, token in _stream_chat(messages, cfg):
            if token:
                yield _sse_event({"token": token})
            elif full_text is not None:
                yield _sse_event({"done": True, "full_text": full_text})
                return
        if full_text is None:
            yield _sse_event({"error": "no response", "full_text": ""})

    return Response(generate(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# 统一评审 (Unified Review) — 合并评审+审计+改写为一个流程
# ---------------------------------------------------------------------------

@review_bp.route("/unified-review", methods=["POST"])
def unified_review_api():
    """统一评审 API：一次调用完成 评审 → 审计 → 改写 完整流程。

    表单参数:
        novel_id: 小说 ID
        chapter_number: 章节号
        version_id: 版本 ID（可选）
        include_rewrite: 是否包含自动改写 (1/0)

    返回:
        综合报告（含评分、维度、问题清单、改写结果）
    """
    from app.services.unified_review import unified_review

    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    version_id = request.form.get("version_id", type=int)
    include_rewrite = request.form.get("include_rewrite", "0") == "1"

    if not novel_id or not chapter_number:
        return jsonify({"error": "novel_id 和 chapter_number 必填"}), 400

    result = unified_review(novel_id, chapter_number, version_id, include_rewrite)
    return jsonify(result)


@review_bp.route("/unified-review-stream", methods=["POST"])
def unified_review_stream_api():
    """统一评审流式版本（SSE）。"""
    from app.services.unified_review import unified_review_stream

    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    version_id = request.form.get("version_id", type=int)
    include_rewrite = request.form.get("include_rewrite", "0") == "1"

    def generate():
        for sse_data in unified_review_stream(novel_id, chapter_number, version_id, include_rewrite):
            yield sse_data

    return Response(generate(), mimetype="text/event-stream")
