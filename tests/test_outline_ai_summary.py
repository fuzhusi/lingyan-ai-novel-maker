"""大纲树节点 AI 摘要（固定格式填入）路由测试。

用户诉求：前端"用于生成的大纲"——大纲树里的章纲/摘要——点生成时
按预设 7 字段格式填入。摘要只填回编辑框，人工确认后才落库。
"""
import pytest

from app import db
from app.models import Novel, OutlineNode

FIXED_SUMMARY = (
    "【本章定位】推进：主角夜探账房\n"
    "【核心事件】1. 主角偷出账册，被巡夜发现\n"
    "【出场人物】林晚照、沈青梧（背景提及）\n"
    "【场景节拍】1. 翻墙入院；2. 惊动夜值\n"
    "【情感基调】紧张→惊疑\n"
    "【伏笔操作】埋设：账册缺页\n"
    "【结尾钩子】暗处有人认出了她"
)


@pytest.fixture
def app():
    from app import create_app as _create_app
    application = _create_app()
    application.config["TESTING"] = True
    with application.app_context():
        db.create_all()
        yield application


def _make_node(app, node_type="chapter", summary=""):
    n = Novel(title="AI摘要测试书")
    db.session.add(n)
    db.session.commit()
    node = OutlineNode(novel_id=n.id, node_type=node_type,
                       title="第一章 夜探", summary=summary)
    db.session.add(node)
    db.session.commit()
    return n.id, node.id


def test_ai_summary_returns_fixed_format(app, client, monkeypatch):
    nid, node_id = _make_node(app)
    from app.services import llm as llm_mod
    captured = {}

    def fake_llm(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return FIXED_SUMMARY

    monkeypatch.setattr(llm_mod, "call_llm_sync", fake_llm)
    resp = client.post(f"/novel/{nid}/outline/{node_id}/ai-summary")
    data = resp.get_json()
    assert resp.status_code == 200 and data["ok"] is True
    for field in ("【本章定位】", "【核心事件】", "【出场人物】", "【场景节拍】",
                  "【情感基调】", "【伏笔操作】", "【结尾钩子】"):
        assert field in data["summary"]
    # prompt 契约单源：system 里带全部字段名
    for field in ("【本章定位】", "【结尾钩子】"):
        assert field in captured["system"]

    # 只回填编辑框，不直接落库
    from app.models import OutlineNode as ON
    with app.app_context():
        assert (ON.query.get(node_id).summary or "") == ""


def test_ai_summary_volume_rejected(app, client):
    nid, node_id = _make_node(app, node_type="volume")
    resp = client.post(f"/novel/{nid}/outline/{node_id}/ai-summary")
    assert resp.status_code == 400


def test_ai_summary_llm_failure(app, client, monkeypatch):
    nid, node_id = _make_node(app)
    from app.services import llm as llm_mod
    from app.services.llm import LLMError

    def boom(**kwargs):
        raise LLMError("厂商不可用")

    monkeypatch.setattr(llm_mod, "call_llm_sync", boom)
    resp = client.post(f"/novel/{nid}/outline/{node_id}/ai-summary")
    assert resp.status_code == 502
    assert "厂商不可用" in resp.get_json()["error"]
