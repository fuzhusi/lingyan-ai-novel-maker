"""Multi-Dimensional Audit API — 17-dimension quality check for chapters and short stories."""
import json
from flask import Blueprint, request, jsonify
from app.models import (db, ChapterVersion, Chapter, Novel, Character,
                        WorldSetting, ChapterSummary, Foreshadowing, CriticReview, ShortStory)
from app.services.audit import run_full_audit, DIMENSIONS, _build_writing_audit_prompt, _run_single_audit
from app.config_utils import get_effective_config, get_model_config
from app.services.prompt_builder import assemble_chapter_context

audit_bp = Blueprint("audit", __name__, url_prefix="/api")


@audit_bp.route("/audit/dimensions")
def list_dimensions():
    """Return all audit dimension definitions."""
    return jsonify({
        dim_id: {
            "name": d["name"],
            "group": d["group"],
            "weight": d["weight"],
            "desc": d["desc"],
        }
        for dim_id, d in DIMENSIONS.items()
    })


@audit_bp.route("/audit/run", methods=["POST"])
def run_audit():
    """Run full 17-dimension audit on a chapter version.

    Form params:
        version_id: chapter version ID
        novel_id: novel ID
        chapter_number: chapter number
    """
    version_id = request.form.get("version_id", type=int)
    novel_id = request.form.get("novel_id", type=int)
    chapter_number = request.form.get("chapter_number", type=int)

    if not version_id:
        return jsonify({"error": "version_id required"}), 400

    version = ChapterVersion.query.get_or_404(version_id)
    chapter = version.chapter
    novel = Novel.query.get(novel_id) if novel_id else chapter.novel
    cfg = get_effective_config(novel, agent_type="audit")

    # Gather context
    ctx = {}
    if novel_id and chapter_number:
        ctx = assemble_chapter_context(novel_id, chapter_number, db)

    # Get all foreshadowing items
    all_fs = []
    if novel_id:
        fs_items = Foreshadowing.query.filter_by(novel_id=novel_id).filter(
            Foreshadowing.status.in_(["open", "planned", "buried", "advancing", "reclaimable"])
        ).all()
        all_fs = [{
            "id": f.id, "description": f.description, "status": f.status,
            "planted_chapter": f.planted_chapter, "importance": f.importance,
        } for f in fs_items]

    # Run audit
    result = run_full_audit(
        chapter_content=version.content,
        outline=chapter.outline,
        chapter_number=chapter_number or chapter.chapter_number,
        characters=ctx.get("characters", []),
        world_settings=ctx.get("world_settings", []),
        summaries=ctx.get("summaries", []),
        foreshadowing_items=all_fs,
        novel_title=novel.title if novel else "",
        cfg=cfg,
    )

    # Save audit result as a CriticReview with dimension data
    review = CriticReview(
        version_id=version_id,
        overall_score=result["overall_score"],
        dimension_scores_json=json.dumps([
            {"name": DIMENSIONS[d]["name"], "score": r["score"], "group": r["group"]}
            for d, r in result["dimensions"].items()
        ], ensure_ascii=False),
        annotations_json=json.dumps(result["issues"][:20], ensure_ascii=False),
        overall_comment=f"[{result['grade']}] {result['summary']}",
        full_response=json.dumps(result, ensure_ascii=False),
    )
    db.session.add(review)
    db.session.commit()

    return jsonify(result)


@audit_bp.route("/audit/quick", methods=["POST"])
def quick_audit():
    """Quick audit — run only the writing quality agent (AI artifacts check).

    Faster than full audit, focused on the most impactful dimension.
    """
    version_id = request.form.get("version_id", type=int)
    if not version_id:
        return jsonify({"error": "version_id required"}), 400

    version = ChapterVersion.query.get_or_404(version_id)
    novel = version.chapter.novel
    cfg = get_effective_config(novel, agent_type="audit")

    messages = _build_writing_audit_prompt(version.content)
    result = _run_single_audit("writing", messages, cfg)

    return jsonify(result)


# ---------------------------------------------------------------------------
# Short Story Audit
# ---------------------------------------------------------------------------

@audit_bp.route("/audit/short-story", methods=["POST"])
def short_story_audit():
    """Run 17-dimension audit on a short story.

    Form params:
        story_id: ShortStory ID
    """
    story_id = request.form.get("story_id", type=int)
    if not story_id:
        return jsonify({"error": "story_id required"}), 400

    story = ShortStory.query.get_or_404(story_id)
    if not story.content:
        return jsonify({"error": "故事内容为空，无法审计"}), 400

    cfg = get_model_config(agent_type="audit")

    # Short story has no characters/world/foreshadowing tables,
    # but we can use the story's own fields as context
    characters = []
    if story.character_desc:
        characters = [{"name": "角色", "personality": story.character_desc}]

    result = run_full_audit(
        chapter_content=story.content,
        outline=story.concept or story.inspiration,
        chapter_number=1,
        characters=characters,
        world_settings=[],
        summaries=[],
        foreshadowing_items=[],
        novel_title=story.title,
        cfg=cfg,
        is_short_story=True,  # 短篇模式，降低世界观权重
    )

    # 持久化审计结果到最新评审记录（页面刷新后可恢复展示）
    from app.models import ShortStoryVersion, ShortStoryReview
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    if not versions and story.content:
        ver = ShortStoryVersion(story_id=story_id, version_number=1,
                                content=story.content, source="ai")
        db.session.add(ver)
        db.session.commit()
        versions = [ver]
    if versions:
        review = ShortStoryReview.query.filter_by(version_id=versions[0].id).order_by(
            ShortStoryReview.id.desc()).first()
        if not review:
            review = ShortStoryReview(version_id=versions[0].id)
            db.session.add(review)
        review.audit_json = json.dumps(result, ensure_ascii=False)
        db.session.commit()

    return jsonify(result)


@audit_bp.route("/audit/short-story/quick", methods=["POST"])
def short_story_quick_audit():
    """Quick audit for short story — AI artifacts check only."""
    story_id = request.form.get("story_id", type=int)
    if not story_id:
        return jsonify({"error": "story_id required"}), 400

    story = ShortStory.query.get_or_404(story_id)
    if not story.content:
        return jsonify({"error": "故事内容为空"}), 400

    cfg = get_model_config(agent_type="audit")
    messages = _build_writing_audit_prompt(story.content)
    result = _run_single_audit("writing", messages, cfg)

    return jsonify(result)
