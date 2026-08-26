# -*- coding: utf-8 -*-
"""双恶毒编辑盲审实验室（cruel_review）测试。"""
import json

import pytest

from app.models import db, ShortStory
from app.routes.short_story.cruel_review import (
    EDITORS, build_editor_messages, run_dual_review,
)


@pytest.fixture
def probe_story(app):
    """临时探针短篇，用完即删。"""
    s = ShortStory(title="盲审探针", mode="careful",
                   content="他把碗端起来，又放下。饭粒粘在筷子尖上，半天没夹起来。")
    db.session.add(s)
    db.session.commit()
    yield s
    db.session.delete(s)
    db.session.commit()


class TestPrompts:
    def test_two_editors_have_distinct_personas(self):
        assert len(EDITORS) == 2
        assert EDITORS[0]["system"] != EDITORS[1]["system"]

    def test_blind_prompt_contains_only_content(self):
        """盲审铁律：user 消息里除正文外不应有任何策划上下文。"""
        content = "夜风穿过巷口，烧烤摊的铁签子翻了一下。"
        msgs = build_editor_messages(EDITORS[0]["system"], content)
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert content in msgs[1]["content"]
        # 防泄漏：不应出现任何大纲/设定/主题等上下文关键词
        for leaked in ("大纲", "人物设定", "世界观", "主题基调", "剧情节点"):
            assert leaked not in msgs[1]["content"], f"盲审被污染: {leaked}"

    def test_output_contract_in_system(self):
        for ed in EDITORS:
            assert "【三大致命伤】" in ed["system"]
            assert "引用原文" in ed["system"]


class TestDualReview:
    def test_run_returns_both_editors(self, app, monkeypatch):
        def fake_call(model, messages, **kwargs):
            name = "阎浮" if "毙稿机" in messages[0]["content"] else "白骨"
            return f"【总评】{name}：弃稿。"

        import app.routes.short_story.cruel_review as mod
        monkeypatch.setattr(mod, "call_llm_sync", fake_call)

        rep = run_dual_review("正文样本。")
        keys = {e["key"] for e in rep["editors"]}
        assert keys == {"yafu", "baigu"}
        reviews = {e["key"]: e["review"] for e in rep["editors"]}
        assert "阎浮" in reviews["yafu"]
        assert "白骨" in reviews["baigu"]


class TestRoutes:
    def test_page_renders(self, client, probe_story):
        resp = client.get(f"/short/{probe_story.id}/cruel")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "盲审实验室" in html and "毙稿机" in html

    def test_page_404_for_missing_story(self, client):
        assert client.get("/short/999999/cruel").status_code == 404

    def test_run_rejects_empty_content(self, client):
        s = ShortStory(title="空正文探针", mode="careful", content="")
        db.session.add(s)
        db.session.commit()
        try:
            resp = client.post(f"/short/{s.id}/cruel/run")
            assert resp.status_code == 400
            assert "还没有正文" in resp.get_json()["error"]
        finally:
            db.session.delete(s)
            db.session.commit()

    def test_run_with_mocked_llm(self, client, probe_story, monkeypatch):
        def fake_call(model, messages, **kwargs):
            return "【判决】弃稿。"

        import app.routes.short_story.cruel_review as mod
        monkeypatch.setattr(mod, "call_llm_sync", fake_call)

        resp = client.post(f"/short/{probe_story.id}/cruel/run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["editors"]) == 2
        assert all(e["review"] for e in data["editors"])
