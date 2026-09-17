"""应用基础设施：全局 errorhandler + 日志配置。

背景：2026-09 审计发现全项目零日志配置、无全局 errorhandler——
未捕获异常直接落 Werkzeug 默认 500 页且无持久现场。
"""
import logging
import logging.handlers

from app import _setup_logging


def test_logging_configured(app):
    logger = logging.getLogger("app")
    handlers = logger.handlers
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
    # propagate=False：避免与 root 重复输出
    assert logger.propagate is False


def test_setup_logging_idempotent():
    import logging
    before = len(logging.getLogger("app").handlers)
    _setup_logging(None)
    _setup_logging(None)
    assert len(logging.getLogger("app").handlers) == before


def test_unhandled_exception_responses(app, client, monkeypatch):
    """JSON 路径回 JSON 500；页面路径回文本提示。

    用 monkeypatch 替换已有视图函数触发异常——session 级 app 在首个请求后
    禁止再注册路由（Flask setup finished），只能动 view_functions。
    """
    def _boom_api():
        raise RuntimeError("boom-test")

    def _boom_page():
        raise ValueError("page-boom")

    monkeypatch.setitem(app.view_functions, "generate.generate_stream", _boom_api)
    resp = client.post("/api/generate-stream")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["error"] == "服务器内部错误"
    assert "boom-test" in data["detail"]

    monkeypatch.setitem(app.view_functions, "novel.index", _boom_page)
    resp2 = client.get("/")
    assert resp2.status_code == 500
    assert "logs/lingyan.log" in resp2.get_data(as_text=True)


def test_host_allowlist_blocks_rebinding(client):
    """DNS rebinding 纵深：Host 为域名且不在白名单 → 403；
    localhost 与 IP 字面量放行。"""
    resp = client.get("/", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403

    resp = client.get("/", headers={"Host": "localhost:5000"})
    assert resp.status_code == 200

    resp = client.get("/", headers={"Host": "127.0.0.1:5000"})
    assert resp.status_code == 200


def test_llm_call_metering_independent_connection(app):
    """计量走独立连接（审计 P1-2）：正常落库；调用方挂起事务时不被连带提交，
    锁竞争下计量快速放弃（250ms busy_timeout）而非阻塞。"""
    from app.services.llm import _record_llm_call
    from app.models import db, Novel
    from sqlalchemy import text as _sql_text
    with app.app_context():
        _record_llm_call("sync", "test-model", True, 123, 100, 50, "")
        rows = db.session.execute(
            _sql_text("SELECT kind, model, ok FROM llm_calls ORDER BY id DESC LIMIT 1")
        ).fetchall()
        assert rows and rows[0].kind == "sync" and rows[0].model == "test-model"

    with app.app_context():
        baseline = db.session.execute(
            _sql_text("SELECT COUNT(*) FROM llm_calls")).scalar()
        n = Novel(title="计量测试书")
        db.session.add(n)
        db.session.flush()  # 打开调用方写事务
        _record_llm_call("sync", "contended", True, 1, 1, 1, "")  # 应快速放弃并只留警告
        db.session.rollback()  # 小说回滚
        after = db.session.execute(_sql_text("SELECT COUNT(*) FROM llm_calls")).scalar()
        assert after == baseline  # 竞争中的计量被放弃，且没有连带提交小说
        assert Novel.query.filter_by(title="计量测试书").count() == 0


def test_http_exception_passthrough(client):
    # 404 等正常 HTTP 错误不落 errorhandler 兜底，保持原生语义
    resp = client.get("/api/definitely-not-exists")
    assert resp.status_code == 404


def test_novel_list_page_renders(app, client):
    """回归：/novel/ 列表页曾因误删 Character/WorldSetting 导入整页 500——
    builder 单测全绿但路由层炸了，路由级测试必须补位。"""
    from app import db
    from app.models import Novel, Character, WorldSetting
    with app.app_context():
        n = Novel(title="列表页回归书", genre="都市")
        db.session.add(n)
        db.session.commit()
        db.session.add_all([
            Character(novel_id=n.id, name="甲"),
            WorldSetting(novel_id=n.id, category="地理", title="临安城", content="江南大城"),
        ])
        db.session.commit()
        nid = n.id
    resp = client.get(f"/novel/{nid}/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "列表页回归书" in html
