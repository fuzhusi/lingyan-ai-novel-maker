"""知识库模块 — 角色、世界观、大纲、伏笔管理。"""
from flask import Blueprint

knowledge_bp = Blueprint("knowledge", __name__, url_prefix="/novel/<int:novel_id>")

# Import sub-modules to register their routes on the blueprint
from app.routes.knowledge import characters    # noqa: F401, E402
from app.routes.knowledge import world          # noqa: F401, E402
from app.routes.knowledge import outline        # noqa: F401, E402
from app.routes.knowledge import foreshadowing  # noqa: F401, E402
