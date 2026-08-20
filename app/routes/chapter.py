import json as _json
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.models import db, Novel, Chapter, ChapterVersion, OutlineNode, Character
from app.services.text_cleaner import clean_ai_text
from app.services.deai_agent import deai_process

chapter_bp = Blueprint("chapter", __name__, url_prefix="/novel/<int:novel_id>")


@chapter_bp.route("/")
def chapter_list(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.chapter_number).all()
    # Build outline node map for chapters
    outline_nodes = {n.id: n for n in OutlineNode.query.filter_by(novel_id=novel_id).all()}
    return render_template("chapter_list.html", novel=novel, chapters=chapters,
                           outline_nodes=outline_nodes)


@chapter_bp.route("/chapter/create", methods=["POST"])
def create_chapter(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    title = request.form.get("title", "").strip()
    chapter_number = request.form.get("chapter_number", type=int)
    outline = request.form.get("outline", "")
    user_directive = request.form.get("user_directive", "")
    outline_node_id = request.form.get("outline_node_id", type=int) or None

    if not chapter_number:
        max_num = db.session.query(db.func.max(Chapter.chapter_number)).filter_by(novel_id=novel_id).scalar()
        chapter_number = (max_num or 0) + 1

    chapter = Chapter(
        novel_id=novel_id,
        chapter_number=chapter_number,
        title=title,
        outline=outline,
        user_directive=user_directive,
        outline_node_id=outline_node_id,
    )
    db.session.add(chapter)
    db.session.commit()
    return redirect(url_for("chapter.chapter_list", novel_id=novel_id))


@chapter_bp.route("/chapter/<int:chapter_number>/write")
def write_chapter(novel_id, chapter_number):
    novel = Novel.query.get_or_404(novel_id)
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    versions = ChapterVersion.query.filter_by(chapter_id=chapter.id).order_by(ChapterVersion.version_number.desc()).all()
    versions_data = [
        {"id": v.id, "version_number": v.version_number, "content": v.content[:200],
         "source": v.source, "created_at": v.created_at}
        for v in versions
    ]

    # Build outline node context if chapter is linked
    outline_context = None
    if chapter.outline_node_id:
        node = OutlineNode.query.get(chapter.outline_node_id)
        if node:
            # Get parent volume
            parent_volume = None
            if node.parent_id:
                p = OutlineNode.query.get(node.parent_id)
                if p and p.node_type == "volume":
                    parent_volume = p

            # Get scene children
            scene_nodes = OutlineNode.query.filter_by(
                parent_id=node.id, node_type="scene"
            ).order_by(OutlineNode.sort_order).all()

            outline_context = {
                "node": node,
                "volume": parent_volume,
                "scenes": scene_nodes,
            }

    # 本章出场角色（前端勾选，控制生成时注入哪些角色档案）
    characters = Character.query.filter_by(novel_id=novel_id).order_by(Character.id).all()

    return render_template("chapter_write.html", novel=novel, chapter=chapter,
                           versions=versions, versions_json=_json.dumps(versions_data),
                           novel_genre=novel.genre, novel_synopsis=novel.synopsis,
                           novel_world_intro=novel.world_intro,
                           characters=characters,
                           outline_context=outline_context)


@chapter_bp.route("/chapter/<int:chapter_number>/save-outline", methods=["POST"])
def save_outline(novel_id, chapter_number):
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    outline = request.form.get("outline", "")
    if outline:
        chapter.outline = outline
        db.session.commit()
        return jsonify({"ok": True})
    return jsonify({"ok": False})


@chapter_bp.route("/chapter/<int:chapter_number>/save-version", methods=["POST"])
def save_version(novel_id, chapter_number):
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    content = clean_ai_text(request.form.get("content", ""))
    source = request.form.get("source", "ai")
    # Auto apply de-AI processing for AI-generated content
    if source == "ai" and content:
        content = deai_process(content)
    prompt_used = request.form.get("prompt_used", "")
    model_params_json = request.form.get("model_params_json", "{}")

    max_ver = db.session.query(db.func.max(ChapterVersion.version_number)).filter_by(chapter_id=chapter.id).scalar()
    version_number = (max_ver or 0) + 1

    version = ChapterVersion(
        chapter_id=chapter.id,
        version_number=version_number,
        content=content,
        source=source,
        prompt_used=prompt_used,
        model_params_json=model_params_json,
    )
    db.session.add(version)
    db.session.commit()
    return jsonify({"version_number": version_number, "id": version.id})


@chapter_bp.route("/chapter/<int:chapter_number>/version/<int:version_id>")
def get_version(novel_id, chapter_number, version_id):
    version = ChapterVersion.query.get_or_404(version_id)
    return jsonify({
        "id": version.id,
        "version_number": version.version_number,
        "content": version.content,
        "source": version.source,
        "prompt_used": version.prompt_used,
        "created_at": version.created_at,
    })


@chapter_bp.route("/chapter/<int:chapter_number>/version/<int:version_id>/delete", methods=["POST"])
def delete_version(novel_id, chapter_number, version_id):
    version = ChapterVersion.query.get_or_404(version_id)
    # Delete associated reviews first
    from app.models import CriticReview
    CriticReview.query.filter_by(version_id=version_id).delete()
    db.session.delete(version)
    db.session.commit()
    return jsonify({"ok": True})


@chapter_bp.route("/chapter/<int:chapter_number>/delete", methods=["POST"])
def delete_chapter(novel_id, chapter_number):
    chapter = Chapter.query.filter_by(novel_id=novel_id, chapter_number=chapter_number).first_or_404()
    # Delete associated reviews, versions, summary, memory
    from app.models import CriticReview, ChapterSummary, ChapterMemory
    for v in chapter.versions:
        CriticReview.query.filter_by(version_id=v.id).delete()
    ChapterVersion.query.filter_by(chapter_id=chapter.id).delete()
    ChapterSummary.query.filter_by(chapter_id=chapter.id).delete()
    ChapterMemory.query.filter_by(chapter_id=chapter.id).delete()
    db.session.delete(chapter)
    db.session.commit()
    return redirect(url_for("chapter.chapter_list", novel_id=novel_id))
