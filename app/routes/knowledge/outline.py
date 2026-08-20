"""大纲管理路由：树形 CRUD + 从大纲创建章节。"""
from flask import render_template, request, redirect, url_for
from app.models import db, Novel, OutlineNode, Chapter
from app.routes.knowledge import knowledge_bp


@knowledge_bp.route("/outline")
def outline_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    nodes = OutlineNode.query.filter_by(novel_id=novel_id).order_by(
        OutlineNode.parent_id.nullsfirst(), OutlineNode.sort_order
    ).all()
    chapters = Chapter.query.filter_by(novel_id=novel_id).all()
    node_chapter_map = {}
    for ch in chapters:
        if ch.outline_node_id:
            node_chapter_map[ch.outline_node_id] = ch
    return render_template("outline.html", novel=novel, nodes=nodes,
                           node_chapter_map=node_chapter_map, chapters=chapters)


@knowledge_bp.route("/outline/<int:node_id>/create-chapter", methods=["POST"])
def create_chapter_from_outline(novel_id, node_id):
    """Create a chapter from an outline node, pre-filling title and outline."""
    node = OutlineNode.query.get_or_404(node_id)

    scene_summaries = []
    children = OutlineNode.query.filter_by(parent_id=node.id).order_by(
        OutlineNode.sort_order
    ).all()
    for child in children:
        if child.node_type == "scene":
            scene_summaries.append(f"【{child.title}】{child.summary}")

    outline_text = node.summary or ""
    if scene_summaries:
        outline_text += "\n\n分幕指引：\n" + "\n".join(scene_summaries)

    max_num = db.session.query(
        db.func.max(Chapter.chapter_number)
    ).filter_by(novel_id=novel_id).scalar()
    chapter_number = (max_num or 0) + 1

    chapter = Chapter(
        novel_id=novel_id,
        chapter_number=chapter_number,
        title=node.title,
        outline=outline_text,
        outline_node_id=node.id,
    )
    db.session.add(chapter)
    db.session.commit()
    return redirect(url_for("chapter.write_chapter",
                            novel_id=novel_id,
                            chapter_number=chapter_number))


@knowledge_bp.route("/outline/create", methods=["POST"])
def create_outline_node(novel_id):
    parent_id = request.form.get("parent_id", type=int) or None
    max_order = db.session.query(db.func.max(OutlineNode.sort_order)).filter_by(
        novel_id=novel_id, parent_id=parent_id
    ).scalar()
    node = OutlineNode(
        novel_id=novel_id,
        parent_id=parent_id,
        sort_order=(max_order or 0) + 1,
        node_type=request.form.get("node_type", "chapter"),
        title=request.form.get("title", "").strip(),
        summary=request.form.get("summary", ""),
    )
    db.session.add(node)
    db.session.commit()
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))


@knowledge_bp.route("/outline/<int:node_id>/edit", methods=["POST"])
def edit_outline_node(novel_id, node_id):
    node = OutlineNode.query.get_or_404(node_id)
    for field in ["title", "summary", "node_type"]:
        val = request.form.get(field, "")
        if val:
            setattr(node, field, val)
    db.session.commit()
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))


@knowledge_bp.route("/outline/<int:node_id>/delete", methods=["POST"])
def delete_outline_node(novel_id, node_id):
    node = OutlineNode.query.get_or_404(node_id)

    def delete_children(parent):
        for child in OutlineNode.query.filter_by(parent_id=parent.id).all():
            delete_children(child)
            db.session.delete(child)
    delete_children(node)
    db.session.delete(node)
    db.session.commit()
    return redirect(url_for("knowledge.outline_page", novel_id=novel_id))
