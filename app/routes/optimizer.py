"""Full Book Optimization API — post-completion quality pass."""
import json
from flask import Blueprint, request, jsonify, Response
from app.models import db, Novel, Chapter, ChapterVersion
from app.services.book_optimizer import diagnose_book, auto_revise_chapter
from app.services.deai_agent import deai_process
from app.config_utils import get_effective_config

optimizer_bp = Blueprint("optimizer", __name__, url_prefix="/api")


@optimizer_bp.route("/novels/<int:novel_id>/optimize/diagnose", methods=["POST"])
def diagnose(novel_id):
    """Diagnose all chapters and return optimization report."""
    from flask import current_app
    novel = Novel.query.get_or_404(novel_id)
    cfg = get_effective_config(novel, agent_type="optimizer")

    report = diagnose_book(novel_id, cfg)
    return jsonify(report)


@optimizer_bp.route("/novels/<int:novel_id>/optimize/deai", methods=["POST"])
def deai_chapter(novel_id):
    """Apply de-AI processing to a specific chapter."""
    chapter_number = request.form.get("chapter_number", type=int)
    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    version = (ChapterVersion.query
               .filter_by(chapter_id=chapter.id)
               .order_by(ChapterVersion.version_number.desc()).first())
    if not version:
        return jsonify({"error": "no version"}), 400

    from app.services.deai_agent import get_deai_stats
    original = version.content
    processed = deai_process(original)
    stats = get_deai_stats(original, processed)

    return jsonify({
        "original": original,
        "processed": processed,
        "stats": stats,
        "changed": original != processed,
    })


@optimizer_bp.route("/novels/<int:novel_id>/optimize/deai/save", methods=["POST"])
def save_deai(novel_id):
    """Save de-AI processed content as a new version."""
    chapter_number = request.form.get("chapter_number", type=int)
    content = request.form.get("content", "")

    if not chapter_number or not content:
        return jsonify({"error": "chapter_number and content required"}), 400

    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()

    max_ver = db.session.query(db.func.max(ChapterVersion.version_number)).filter_by(chapter_id=chapter.id).scalar()
    version = ChapterVersion(
        chapter_id=chapter.id,
        version_number=(max_ver or 0) + 1,
        content=content,
        source="deai",
    )
    db.session.add(version)
    db.session.commit()

    return jsonify({"ok": True, "versionId": version.id})


@optimizer_bp.route("/novels/<int:novel_id>/optimize/revise", methods=["POST"])
def revise_chapter(novel_id):
    """Auto-revise a chapter based on optimization issues."""
    chapter_number = request.form.get("chapter_number", type=int)
    issues_json = request.form.get("issues", "[]")

    if not chapter_number:
        return jsonify({"error": "chapter_number required"}), 400

    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    novel = Novel.query.get(novel_id)
    cfg = get_effective_config(novel, agent_type="optimizer")

    try:
        issues = json.loads(issues_json)
    except json.JSONDecodeError:
        issues = []

    result = auto_revise_chapter(chapter.id, novel_id, chapter_number, issues, cfg)
    if not result:
        return jsonify({"error": "revision failed"}), 500

    return jsonify(result)
