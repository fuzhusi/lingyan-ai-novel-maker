"""双恶毒编辑盲审实验室（短篇深度循环页）。

盲审引擎已提升为正式服务层 app/services/blind_review.py（同时服务
长篇章节、短篇写作页与 /blind/ 工作台）。本模块只保留短篇实验页的
路由封装：单篇直入、审后一键重写、循环再审。
"""
from flask import render_template, request, jsonify

from app.models import ShortStory
from app.services.llm import LLMError
from app.services.blind_review import run_dual_review, run_rewrite
from app.routes.short_story import short_story_bp


@short_story_bp.route("/<int:story_id>/cruel")
def cruel_page(story_id):
    """双恶毒编辑盲审实验室页面。"""
    story = ShortStory.query.get_or_404(story_id)
    content = story.content or ""
    return render_template(
        "short_story/cruel.html",
        story=story,
        word_count=len(content),
        has_content=bool(content.strip()),
    )


@short_story_bp.route("/<int:story_id>/cruel/run", methods=["POST"])
def cruel_run(story_id):
    """运行双编辑盲审，JSON 返回两份审评。

    可选 JSON body {"content": "..."}：审阅自定义文本（如重写后的新稿），
    未提供时使用短篇当前正文——支持「重写 → 再审」循环。
    """
    story = ShortStory.query.get_or_404(story_id)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or story.content or "").strip()
    if not content:
        return jsonify({"error": "该短篇还没有正文，先去写作页生成或保存内容"}), 400

    try:
        result = run_dual_review(content)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    return jsonify({
        "ok": True,
        "story_title": story.title,
        "word_count": len(content),
        "elapsed": result["elapsed"],
        "editors": result["editors"],
    })


@short_story_bp.route("/<int:story_id>/cruel/regenerate", methods=["POST"])
def cruel_regenerate(story_id):
    """把盲审报告返还给 Writer，生成第二稿。

    Body: {"reviews": [{"name","review"},...], "content": "可选原稿覆盖"}
    """
    story = ShortStory.query.get_or_404(story_id)
    data = request.get_json(silent=True) or {}
    original = (data.get("content") or story.content or "").strip()
    if not original:
        return jsonify({"error": "没有可重写的正文"}), 400
    reviews = [r for r in (data.get("reviews") or [])
               if isinstance(r, dict) and (r.get("review") or "").strip()]
    if not reviews:
        return jsonify({"error": "缺少审评内容——请先完成一轮盲审"}), 400

    try:
        result = run_rewrite(original, reviews)
    except LLMError as e:
        return jsonify({"error": f"AI 调用失败：{e}"}), 502

    return jsonify({
        "ok": True, "elapsed": result["elapsed"], "rounds": result["rounds"],
        "content": result["content"],
        "orig_words": len(original), "new_words": len(result["content"]),
    })
