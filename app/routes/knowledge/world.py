"""世界观管理路由：CRUD。"""
from flask import render_template, request, redirect, url_for
from app.models import db, Novel, WorldSetting
from app.routes.knowledge import knowledge_bp


@knowledge_bp.route("/world-settings")
def world_settings_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    settings = WorldSetting.query.filter_by(novel_id=novel_id).order_by(
        WorldSetting.category, WorldSetting.title
    ).all()
    categories = sorted(set(ws.category for ws in settings if ws.category))
    return render_template("world_settings.html", novel=novel, settings=settings, categories=categories)


@knowledge_bp.route("/world-settings/create", methods=["POST"])
def create_world_setting(novel_id):
    ws = WorldSetting(
        novel_id=novel_id,
        category=request.form.get("category", "").strip(),
        title=request.form.get("title", "").strip(),
        content=request.form.get("content", ""),
    )
    db.session.add(ws)
    db.session.commit()
    return redirect(url_for("knowledge.world_settings_page", novel_id=novel_id))


@knowledge_bp.route("/world-settings/<int:ws_id>/edit", methods=["POST"])
def edit_world_setting(novel_id, ws_id):
    ws = WorldSetting.query.get_or_404(ws_id)
    for field in ["category", "title", "content"]:
        val = request.form.get(field, "")
        if val:
            setattr(ws, field, val)
    db.session.commit()
    return redirect(url_for("knowledge.world_settings_page", novel_id=novel_id))


@knowledge_bp.route("/world-settings/<int:ws_id>/delete", methods=["POST"])
def delete_world_setting(novel_id, ws_id):
    ws = WorldSetting.query.get_or_404(ws_id)
    db.session.delete(ws)
    db.session.commit()
    return redirect(url_for("knowledge.world_settings_page", novel_id=novel_id))
