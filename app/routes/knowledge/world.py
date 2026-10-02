"""世界观管理路由：CRUD。"""
from flask import render_template, request, redirect, url_for


def _redirect_back(novel_id, fallback_endpoint):
    """容器页/旧页双入口兼容：表单带 next 时回容器对应 Tab，否则回旧页。"""
    nxt = (request.form.get("next") or "").strip()
    if nxt.startswith("/novel/%d/" % novel_id):
        return redirect(nxt)
    return redirect(url_for(fallback_endpoint, novel_id=novel_id))
from app.models import db, Novel, WorldSetting
from app.services.knowledge_activation import normalize_policy_json as _normalize_policy
from app.routes.knowledge import knowledge_bp


@knowledge_bp.route("/world-settings")
def world_settings_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    settings = WorldSetting.query.filter_by(novel_id=novel_id).order_by(
        WorldSetting.category, WorldSetting.title
    ).all()
    categories = sorted(set(ws.category for ws in settings if ws.category))
    return render_template("world_settings.html", novel=novel, active_nav="world", settings=settings, categories=categories)


@knowledge_bp.route("/world-settings/create", methods=["POST"])
def create_world_setting(novel_id):
    ws = WorldSetting(
        novel_id=novel_id,
        category=request.form.get("category", "").strip(),
        title=request.form.get("title", "").strip(),
        content=request.form.get("content", ""),
        injection_policy=_normalize_policy(request.form.get("injection_policy", "")),
    )
    db.session.add(ws)
    db.session.commit()
    return _redirect_back(novel_id, "knowledge.world_settings_page")


@knowledge_bp.route("/world-settings/<int:ws_id>/edit", methods=["POST"])
def edit_world_setting(novel_id, ws_id):
    ws = WorldSetting.query.get_or_404(ws_id)
    for field in ["category", "title", "content", "injection_policy"]:
        val = request.form.get(field, "")
        if val:
            setattr(ws, field, val)
    db.session.commit()
    return _redirect_back(novel_id, "knowledge.world_settings_page")


@knowledge_bp.route("/world-settings/<int:ws_id>/delete", methods=["POST"])
def delete_world_setting(novel_id, ws_id):
    ws = WorldSetting.query.get_or_404(ws_id)
    db.session.delete(ws)
    db.session.commit()
    return _redirect_back(novel_id, "knowledge.world_settings_page")
