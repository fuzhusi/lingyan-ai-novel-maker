"""双盲审路由 —— 正式审评体系的通用 API 与独立工作台。"""
import json

from flask import Blueprint, render_template, request, jsonify

from app.models import db, ShortStory, Novel, Chapter, ChapterVersion
from app.services.llm import LLMError
from app.services.blind_review import (
    run_dual_review, run_rewrite, resolve_content,
    save_blind_review, get_latest_blind_review,
)

blind_review_bp = Blueprint("blind_review", __name__)


# ---------------------------------------------------------------------------
# 工作台页面
# ---------------------------------------------------------------------------

@blind_review_bp.route("/blind/")
def blind_workbench():
    """双盲审工作台：任选短篇 / 长篇章节 / 自由文本，跑两角色盲审。"""
    stories = ShortStory.query.order_by(ShortStory.id.desc()).limit(50).all()
    novels = Novel.query.order_by(Novel.id.desc()).all()
    chapter_options = []
    for n in novels:
        chapters = (Chapter.query.filter_by(novel_id=n.id)
                    .order_by(Chapter.chapter_number).all())
        for ch in chapters:
            has_content = db.session.query(ChapterVersion.id).filter_by(
                chapter_id=ch.id).first() is not None
            if has_content:
                chapter_options.append({
                    "novel_id": n.id, "novel_title": n.title,
                    "chapter_number": ch.chapter_number, "title": ch.title,
                })
    recent = []
    for r in _recent_reviews(limit=8):
        recent.append(r)
    return render_template(
        "blind.html", stories=stories, chapter_options=chapter_options,
        recent=recent,
    )


def _recent_reviews(limit=8):
    from app.models import BlindReview
    rows = (BlindReview.query.order_by(BlindReview.id.desc())
            .limit(limit).all())
    out = []
    for row in rows:
        try:
            editors = json.loads(row.editors_json or "[]")
        except Exception:
            editors = []
        verdicts = "／".join(
            f"{e.get('verdict') or '?'}" for e in editors) or "-"
        out.append({
            "id": row.id, "kind": row.kind, "title": row.title or "(未命名)",
            "verdicts": verdicts, "word_count": row.word_count,
            "created_at": row.created_at,
        })
    return out


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _resolve_target(payload):
    """从请求 body 解析目标正文与元数据。返回 (text, meta, kind, title) 或错误。"""
    kind = payload.get("kind") or "text"
    content = payload.get("content")
    title = ""
    if kind == "story":
        story = ShortStory.query.get(payload.get("id")) if payload.get("id") else None
        if not story:
            return None, None, None, "短篇不存在"
        title = story.title
    elif kind == "chapter":
        novel = Novel.query.get(payload.get("novel_id")) \
            if payload.get("novel_id") else None
        if not novel:
            return None, None, None, "小说不存在"
        title = f"{novel.title}"
    text, meta = resolve_content(
        kind,
        story_id=payload.get("id"),
        novel_id=payload.get("novel_id"),
        chapter_number=payload.get("chapter_number"),
        version_id=payload.get("version_id"),
        content=content,
    )
    return text, meta, kind, title


@blind_review_bp.route("/api/blind-review/run", methods=["POST"])
def blind_run():
    """运行双盲审。

    Body JSON: {"kind": "story"|"chapter"|"text",
                "id": 短篇ID(kind=story),
                "novel_id"+可选"chapter_number"/"version_id": (kind=chapter),
                "content": 可选正文覆盖（kind=text 必填）}
    """
    payload = request.get_json(silent=True) or {}
    text, meta, kind, title = _resolve_target(payload)
    if text is None:
        return jsonify({"error": meta}), 400

    try:
        result = run_dual_review(text)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    save_blind_review(
        kind, result, word_count=len(text),
        story_id=meta.get("story_id"), version_id=meta.get("version_id"),
        title=title,
    )
    return jsonify({
        "ok": True,
        "kind": kind, "title": title, "word_count": len(text),
        "elapsed": result["elapsed"], "editors": result["editors"],
    })


@blind_review_bp.route("/api/blind-review/rewrite", methods=["POST"])
def blind_rewrite():
    """盲审意见返还 Writer 生成第二稿（建议稿，不自动覆盖任何正文）。

    Body JSON: {"kind": ..., 目标字段同 run,
                "reviews": [{"name","review"}...] 缺省用最近一次记录,
                "include_editors": ["yafu","baigu"] 可选过滤}
    """
    payload = request.get_json(silent=True) or {}
    text, meta, kind, title = _resolve_target(payload)
    if text is None and not (payload.get("content") or "").strip():
        # rewrite 允许对「自定义新稿」再审，这里 text 为空说明连原稿都没有
        return jsonify({"error": meta}), 400

    reviews = [r for r in (payload.get("reviews") or [])
               if isinstance(r, dict) and (r.get("review") or "").strip()]
    include = set(payload.get("include_editors")
                  or [e.get("key") for e in reviews])
    reviews = [r for r in reviews if r.get("key") in include] or reviews
    if not reviews:
        # 回退取最近一次记录：必须按对象限定，防止拿到其他短篇/章节/文本的审评
        if payload.get("id"):
            latest = get_latest_blind_review(story_id=payload["id"])
        elif meta.get("version_id"):
            latest = get_latest_blind_review(version_id=meta["version_id"])
        else:
            latest = get_latest_blind_review(kind="text")
        reviews = [r for r in (latest or {}).get("editors", []) if r.get("review")]
    if not reviews:
        return jsonify({"error": "缺少审评内容——请先完成一轮盲审"}), 400

    writer_agent = "rewrite" if kind == "chapter" else "short_story"
    try:
        result = run_rewrite(text, reviews, writer_agent=writer_agent)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    return jsonify({
        "ok": True, "elapsed": result["elapsed"], "rounds": result["rounds"],
        "content": result["content"],
        "orig_words": len(text), "new_words": len(result["content"]),
    })


@blind_review_bp.route("/api/blind-review/latest")
def blind_latest():
    """查询某对象最近一次盲审（页面恢复展示用）。

    Query: kind=story&id=... 或 kind=chapter&novel_id=&chapter_number=
    """
    kind = request.args.get("kind") or "story"
    if kind == "story":
        sid = request.args.get("id", type=int)
        rec = get_latest_blind_review(story_id=sid) if sid else None
    elif kind == "chapter":
        version_id = request.args.get("version_id", type=int)
        if not version_id:
            ch = Chapter.query.filter_by(
                novel_id=request.args.get("novel_id", type=int),
                chapter_number=request.args.get("chapter_number", type=int),
            ).first() if request.args.get("novel_id") else None
            if not ch:
                return jsonify(None)
            ver = (ChapterVersion.query.filter_by(chapter_id=ch.id)
                   .order_by(ChapterVersion.version_number.desc()).first())
            version_id = ver.id if ver else None
        rec = get_latest_blind_review(version_id=version_id) if version_id else None
    else:
        # text 等其他类型：按类型取全局最近一条
        rec = get_latest_blind_review(kind=kind)
    return jsonify(rec)
