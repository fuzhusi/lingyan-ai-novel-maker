import json
import difflib
import logging
from flask import Blueprint, request, Response, jsonify, current_app
from app.models import db, Chapter, ChapterVersion, CriticReview, Novel
from app.services.prompt_builder import (build_critic_prompt,
                                          build_rewrite_prompt, assemble_chapter_context)
from app.services.llm import stream_llm_tokens, LLMError
from app.services.chapter_approval import (approve_chapter_version, EmptyChapterError,
                                           extract_json_dict as _extract_json_dict)
from app.config_utils import get_effective_config


review_bp = Blueprint("review", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_chat(messages, cfg):
    """流式调用 LLM。

    Yields:
        ("token", str)  —— 增量正文
        ("done", full)  —— 正常结束，携带全文
        ("error", msg)  —— 出错（结构化信号；绝不把 SSE 错误串当 token 混入正文）
    """
    collected = []
    try:
        for token in stream_llm_tokens(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.5), max_tokens=cfg.get("max_tokens", 4096),
        ):
            collected.append(token)
            yield "token", token
        yield "done", "".join(collected)
    except LLMError as e:
        yield "error", str(e)
    except Exception as e:
        yield "error", str(e)


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
        for kind, payload in _stream_chat(messages, cfg):
            if kind == "token":
                yield _sse_event({"token": payload})
            elif kind == "done":
                yield _sse_event({"done": True, "full_text": payload})
                return
            elif kind == "error":
                yield _sse_event({"error": payload})
                return

    return Response(generate(), mimetype="text/event-stream")


@review_bp.route("/review/save", methods=["POST"])
def save_review():
    version_id = request.form.get("version_id", type=int)
    full_response = request.form.get("full_response", "")
    version = ChapterVersion.query.get_or_404(version_id)

    data = _extract_json_dict(full_response)
    if data is not None:
        overall_score = data.get("overall_score")
        overall_comment = data.get("overall_comment", "")
        dimensions = data.get("dimensions", [])
        annotations = data.get("annotations", [])
    else:
        # 解析失败降级为纯文本评论（含围栏原文），不再 500
        overall_score = None
        dimensions = []
        annotations = []
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
    # 审批事务统一走服务层（空内容 400 / 摘要兜底 / 结构化记忆），与 MCP/CLI 同源
    try:
        result = approve_chapter_version(version, generate_summary=True)
    except EmptyChapterError:
        return jsonify({"error": "正文为空，无法审批"}), 400
    return jsonify(result)


@review_bp.route("/tone-converge", methods=["POST"])
def tone_converge():
    """去AI味收敛回滚环：检测 → 定向重写 → 复测，人味分不升自动回滚保留原稿。

    Body: JSON {"text": "...", "novel_id": int?}
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or request.form.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    novel_id = data.get("novel_id") or request.form.get("novel_id", type=int)
    novel = Novel.query.get(novel_id) if novel_id else None
    cfg = get_effective_config(novel, agent_type="rewrite")
    from app.services.tone_convergence import converge_tone
    return jsonify(converge_tone(text, cfg))


@review_bp.route("/condense", methods=["POST"])
def condense():
    """字数超标压缩：保留情节节拍/对话/因果，压描写冗余（目标默认 2500 字）。

    Body: JSON {"text": "...", "novel_id": int?, "target_chars": int?}
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or request.form.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    novel_id = data.get("novel_id") or request.form.get("novel_id", type=int)
    novel = Novel.query.get(novel_id) if novel_id else None
    cfg = get_effective_config(novel, agent_type="rewrite")
    target = data.get("target_chars") or request.form.get("target_chars", type=int) or 2500
    from app.services.tone_convergence import condense_text
    return jsonify(condense_text(text, cfg, target_chars=int(target)))


@review_bp.route("/consistency-check", methods=["POST"])
def consistency_check_api():
    """一致性链（P2）：确定性交叉核对 → 可选 Keepers 裁决。

    Body: JSON {"novel_id", "chapter_number", "text"?, "adjudicate": bool}
    text 缺省取该章最新版本正文。
    """
    data = request.get_json(silent=True) or {}
    novel_id = data.get("novel_id") or request.form.get("novel_id", type=int)
    chapter_number = (data.get("chapter_number")
                      or request.form.get("chapter_number", type=int))
    if not novel_id or not chapter_number:
        return jsonify({"error": "novel_id / chapter_number required"}), 400

    text = (data.get("text") or "").strip()
    if not text:
        chapter = Chapter.query.filter_by(novel_id=novel_id,
                                          chapter_number=chapter_number).first()
        version = (ChapterVersion.query.filter_by(chapter_id=chapter.id)
                   .order_by(ChapterVersion.version_number.desc()).first()) if chapter else None
        if not version:
            return jsonify({"error": "该章暂无正文"}), 400
        text = version.content or ""

    novel = Novel.query.get(novel_id)
    from app.services.consistency_check import run_consistency_check
    report = run_consistency_check(
        text, novel_id, chapter_number, novel=novel,
        adjudicate=bool(data.get("adjudicate") or request.form.get("adjudicate")))
    return jsonify(report)


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

    # 统一意见 Schema（P1）：前端勾选的合并意见逐条注入
    opinions_block = ""
    opinions_raw = request.form.get("opinions", "")
    if opinions_raw:
        try:
            import json as _json
            from app.services.opinions import format_opinions_block
            items = _json.loads(opinions_raw)
            if isinstance(items, list):
                opinions_block = format_opinions_block(
                    [o for o in items if isinstance(o, dict)])
        except Exception:
            logger.warning("opinions 解析失败，忽略勾选意见", exc_info=True)

    messages = build_rewrite_prompt(
        original_content=version.content,
        critic_feedback=critic_feedback,
        novel_title=novel_title,
        chapter_title=chapter.title,
        outline=chapter.outline,
        user_directive=chapter.user_directive,
        db=db,
        author_intent=(chapter.novel.author_intent or "") if chapter.novel else "",
        current_focus=(chapter.novel.current_focus or "") if chapter.novel else "",
        opinions_block=opinions_block,
    )

    cfg = get_effective_config(chapter.novel, agent_type="rewrite")

    def generate():
        for kind, payload in _stream_chat(messages, cfg):
            if kind == "token":
                yield _sse_event({"token": payload})
            elif kind == "done":
                yield _sse_event({"done": True, "full_text": payload})
                return
            elif kind == "error":
                yield _sse_event({"error": payload})
                return

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
    """统一评审流式版本（SSE）。

    注意：SSE 生成器在请求上下文销毁后才被迭代，内部有 DB 访问，
    必须显式推回 app context（否则 Flask-SQLAlchemy 抛
    RuntimeError: Working outside of application context）。
    """
    from app.services.unified_review import unified_review_stream

    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)
    version_id = request.form.get("version_id", type=int)
    include_rewrite = request.form.get("include_rewrite", "0") == "1"

    app_obj = current_app._get_current_object()

    def generate():
        with app_obj.app_context():
            for sse_data in unified_review_stream(novel_id, chapter_number, version_id, include_rewrite):
                yield sse_data

    return Response(generate(), mimetype="text/event-stream")
