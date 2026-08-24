from flask import Flask, session, request, jsonify
from datetime import timedelta
from app.config import AppConfig
from app.models import db, init_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(AppConfig)

    # Session 配置（默认7天）
    app.permanent_session_lifetime = timedelta(days=7)

    db.init_app(app)
    init_db(app)

    # 请求结束后清空 provider 缓存
    from app.config_utils import _reset_provider_cache
    app.teardown_appcontext(lambda exc: _reset_provider_cache())

    from app.routes.novel import novel_bp
    from app.routes.chapter import chapter_bp
    from app.routes.generate import generate_bp
    from app.routes.knowledge import knowledge_bp
    from app.routes.review import review_bp
    from app.routes.templates_lib import templates_bp
    from app.routes.settings import settings_bp
    from app.routes.export import export_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.story_state import story_state_bp
    from app.routes.relations import relations_bp
    from app.routes.pipeline import pipeline_bp
    from app.routes.short_story import short_story_bp
    from app.routes.audit import audit_bp
    from app.services.causal_chain import causal_bp
    from app.routes.optimizer import optimizer_bp
    from app.services.vector_memory import memory_bp
    from app.services.style_fingerprint import style_bp
    from app.services.skill_system import skill_bp
    from app.services.temporal_truth import truth_bp
    from app.routes.auth import auth_bp
    from app.routes.sample_data import sample_bp
    from app.routes.outline_templates import templates_bp as outline_templates_bp
    from app.routes.plagiarize import plagiarize_bp
    from app.routes.llm_settings import llm_settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(sample_bp)
    app.register_blueprint(outline_templates_bp)
    app.register_blueprint(plagiarize_bp)
    app.register_blueprint(llm_settings_bp)
    app.register_blueprint(novel_bp)
    app.register_blueprint(chapter_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(story_state_bp)
    app.register_blueprint(relations_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(short_story_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(causal_bp)
    app.register_blueprint(optimizer_bp)
    app.register_blueprint(memory_bp)
    app.register_blueprint(style_bp)
    app.register_blueprint(skill_bp)
    app.register_blueprint(truth_bp)

    # ---------------------------------------------------------------------------
    # CSRF 轻量防护：拒绝浏览器标记为跨站的不安全请求。
    # 现代浏览器对跨站 POST/PUT/PATCH/DELETE 均带 Sec-Fetch-Site: cross-site 头，
    # 据此可在不改动任何模板的前提下阻断「外部网页静默表单打向本服务」的经典 CSRF
    # （如自动提交 /novel/delete-all 清空数据）。无此头的旧客户端放行（fail-open），
    # 配合"仅绑定 127.0.0.1"的默认部署形成纵深。
    # ---------------------------------------------------------------------------
    unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    allowed_fetch_sites = {"same-origin", "same-site", "none"}

    @app.before_request
    def _reject_cross_site_writes():
        if request.method not in unsafe_methods:
            return None
        site = request.headers.get("Sec-Fetch-Site", "").lower()
        if site and site not in allowed_fetch_sites:
            return jsonify({"error": "cross-site write request rejected"}), 403
        return None

    return app
