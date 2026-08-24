"""短篇版本管理路由：版本列表、保存、加载、删除、审批。"""
import json
from flask import request, jsonify
from app.models import db, ShortStory, ShortStoryVersion
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process
from app.routes.short_story import short_story_bp


@short_story_bp.route("/<int:story_id>/versions")
def list_versions(story_id):
    """List all versions of a short story."""
    story = ShortStory.query.get_or_404(story_id)
    versions = ShortStoryVersion.query.filter_by(story_id=story_id).order_by(
        ShortStoryVersion.version_number.desc()).all()
    return jsonify([{
        "id": v.id,
        "versionNumber": v.version_number,
        "source": v.source,
        "approved": v.approved,
        "contentLength": len(v.content) if v.content else 0,
        "createdAt": v.created_at,
    } for v in versions])


@short_story_bp.route("/<int:story_id>/save-version", methods=["POST"])
def save_version(story_id):
    """Save current content as a new version."""
    story = ShortStory.query.get_or_404(story_id)
    content = request.form.get("content", story.content)
    source = request.form.get("source", "human")

    if not content:
        return jsonify({"error": "content empty"}), 400

    max_ver = db.session.query(db.func.max(ShortStoryVersion.version_number)).filter_by(
        story_id=story_id).scalar()
    version_number = (max_ver or 0) + 1

    version = ShortStoryVersion(
        story_id=story_id,
        version_number=version_number,
        content=deai_process(clean_ai_text(content)) if source == "ai" else clean_ai_text(content),
        source=source,
    )
    db.session.add(version)

    # Also update story content
    story.content = deai_process(clean_ai_text(content)) if source == "ai" else clean_ai_text(content)
    story.status = "done"
    db.session.commit()

    return jsonify({"ok": True, "versionId": version.id, "versionNumber": version_number})


@short_story_bp.route("/<int:story_id>/version/<int:version_id>")
def get_version(story_id, version_id):
    """Get a specific version's content."""
    # 归属校验：版本必须属于 URL 指定的短篇，防止跨实体读写
    version = ShortStoryVersion.query.filter_by(id=version_id, story_id=story_id).first_or_404()
    return jsonify({
        "id": version.id,
        "versionNumber": version.version_number,
        "content": version.content,
        "source": version.source,
        "approved": version.approved,
    })


@short_story_bp.route("/<int:story_id>/version/<int:version_id>/load", methods=["POST"])
def load_version(story_id, version_id):
    """Load a version as the current content."""
    story = ShortStory.query.get_or_404(story_id)
    version = ShortStoryVersion.query.filter_by(id=version_id, story_id=story_id).first_or_404()
    story.content = version.content
    db.session.commit()
    return jsonify({"ok": True, "content": version.content})


@short_story_bp.route("/<int:story_id>/version/<int:version_id>/delete", methods=["POST"])
def delete_version(story_id, version_id):
    """Delete a version."""
    version = ShortStoryVersion.query.filter_by(id=version_id, story_id=story_id).first_or_404()
    db.session.delete(version)
    db.session.commit()
    return jsonify({"ok": True})


@short_story_bp.route("/<int:story_id>/approve/<int:version_id>", methods=["POST"])
def approve_version(story_id, version_id):
    """Approve a version."""
    version = ShortStoryVersion.query.filter_by(id=version_id, story_id=story_id).first_or_404()
    version.approved = True
    db.session.commit()
    return jsonify({"ok": True})
