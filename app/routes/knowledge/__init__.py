"""知识库模块 — 角色、世界观、大纲、伏笔管理。"""
from flask import Blueprint, render_template, request

knowledge_bp = Blueprint("knowledge", __name__, url_prefix="/novel/<int:novel_id>")

# Import sub-modules to register their routes on the blueprint
from app.routes.knowledge import characters    # noqa: F401, E402
from app.routes.knowledge import world          # noqa: F401, E402
from app.routes.knowledge import outline        # noqa: F401, E402
from app.routes.knowledge import foreshadowing  # noqa: F401, E402


@knowledge_bp.route("/knowledge")
def knowledge_page(novel_id):
    """知识库容器页：人物库/世界观/伏笔三 Tab（大纲保持独立工作台入口）。"""
    from app import db
    from app.models import Novel, Character, WorldSetting, Foreshadowing

    novel = Novel.query.get_or_404(novel_id)
    active_tab = request.args.get("tab", "characters")
    if active_tab not in ("characters", "world", "foreshadowing"):
        active_tab = "characters"

    context = {"novel": novel, "active_nav": "knowledge", "active_tab": active_tab}
    if active_tab == "characters":
        context["characters"] = (Character.query
                                 .filter_by(novel_id=novel_id)
                                 .order_by(Character.name).all())
    elif active_tab == "world":
        settings = (WorldSetting.query
                    .filter_by(novel_id=novel_id)
                    .order_by(WorldSetting.category, WorldSetting.title)
                    .all())
        context["settings"] = settings
        context["categories"] = sorted(set(ws.category for ws in settings
                                         if ws.category))
    else:
        context["items"] = (Foreshadowing.query
                            .filter_by(novel_id=novel_id)
                            .order_by(Foreshadowing.status,
                                      Foreshadowing.created_at.desc())
                            .all())
        rows = db.session.execute(
            db.text("SELECT chapter_number FROM chapters "
                    "WHERE novel_id = :nid ORDER BY chapter_number"),
            {"nid": novel_id}).fetchall()
        context["chapter_nums"] = [r[0] for r in rows]
    return render_template("knowledge.html", **context)
