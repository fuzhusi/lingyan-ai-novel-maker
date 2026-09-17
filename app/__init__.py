import json
import logging
import logging.handlers
import os

from flask import Flask, request, jsonify
from datetime import timedelta
from app.config import AppConfig
from app.models import db, init_db

_LOG_CONFIGURED = False


def _setup_logging(app):
    """日志配置（全程只配一次）：app.* 命名空间 → 控制台 + logs/lingyan.log 轮转；
    其他库（sqlalchemy/werkzeug 等）→ 仅文件，WARNING 起。
    项目此前零日志配置，LLM 重试失败、盲审落库失败等关键故障没有持久现场。
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    _LOG_CONFIGURED = True
    level = logging.DEBUG if os.getenv("LINGYAN_DEBUG", "").strip() == "1" else logging.INFO
    log_dir = os.getenv("LINGYAN_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    app_logger.propagate = False
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    app_logger.addHandler(console)
    file_h = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "lingyan.log"),
        maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_h.setFormatter(fmt)
    app_logger.addHandler(file_h)

    root = logging.getLogger()
    root.setLevel(max(level, logging.WARNING))
    root.addHandler(file_h)
    # 第三方库（waitress "Serving on"、sqlalchemy 报警等）的 WARNING 仍要进控制台——
    # 否则启动后终端一片安静，用户会误以为服务没起来
    root_console = logging.StreamHandler()
    root_console.setFormatter(fmt)
    root.addHandler(root_console)


def create_app():
    app = Flask(__name__)
    app.config.from_object(AppConfig)
    _setup_logging(app)

    # Session 配置（默认7天）
    app.permanent_session_lifetime = timedelta(days=7)

    db.init_app(app)
    init_db(app)

    # 模板过滤器：人物 status_json.plan → 可读计划行（拆书成果可见性）

    @app.template_filter("plan_summary")
    def _plan_summary(status_json):
        try:
            plan = (json.loads(status_json or "{}").get("plan")) or {}
        except Exception:
            return ""
        parts = []
        if plan.get("first_chapter"):
            parts.append(f"首现第{plan['first_chapter']}章")
        if plan.get("exit_chapter"):
            parts.append(f"退场第{plan['exit_chapter']}章（{plan.get('exit_mode') or '收线'}）")
        return " · ".join(parts)

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
    from app.routes.blind_review import blind_review_bp
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
    from app.routes.resources import resources_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(sample_bp)
    app.register_blueprint(outline_templates_bp)
    app.register_blueprint(plagiarize_bp)
    app.register_blueprint(llm_settings_bp)
    app.register_blueprint(resources_bp)
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
    app.register_blueprint(blind_review_bp)
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
    import ipaddress
    unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    allowed_fetch_sites = {"same-origin", "same-site", "none"}
    # Host 白名单：localhost/IP 字面量放行（本机或局域网直连），其他域名默认拒绝——
    # 封死 DNS rebinding（恶意域名解析到 127.0.0.1 后 Host 头仍是该域名）。
    # 反代域名部署用 LINGYAN_ALLOWED_HOSTS 放行。
    allowed_hosts = {"localhost"}
    allowed_hosts |= {h.strip().lower() for h in
                      os.getenv("LINGYAN_ALLOWED_HOSTS", "").split(",") if h.strip()}

    @app.before_request
    def _reject_foreign_host():
        hostname = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if not hostname or hostname in allowed_hosts:
            return None
        try:
            ipaddress.ip_address(hostname)
            return None  # IP 直连（本机/局域网）放行
        except ValueError:
            return jsonify({"error": f"host '{hostname}' not allowed"}), 403

    @app.before_request
    def _reject_cross_site_writes():
        if request.method not in unsafe_methods:
            return None
        site = request.headers.get("Sec-Fetch-Site", "").lower()
        if site and site not in allowed_fetch_sites:
            return jsonify({"error": "cross-site write request rejected"}), 403
        return None

    # ---------------------------------------------------------------------------
    # 全局兜底 errorhandler：此前未捕获异常直接落 Werkzeug 默认 500 页，
    # 连日志都没有。HTTPException（404/405 等正常错误）交还原生处理；
    # 真正的未捕获异常：回滚事务、记录堆栈、按请求类型返回 JSON/文本。
    # ---------------------------------------------------------------------------
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def _unhandled_exception(exc):
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("未捕获异常 %s %s", request.method, request.path)
        try:
            db.session.rollback()
        except Exception:
            pass
        wants_json = (request.path.startswith("/api/")
                      or request.accept_mimetypes.best == "application/json")
        if wants_json:
            return jsonify({"error": "服务器内部错误", "detail": str(exc)}), 500
        return "服务器内部错误，详情请查看 logs/lingyan.log", 500

    return app
