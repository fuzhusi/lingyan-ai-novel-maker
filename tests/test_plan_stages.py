"""短篇分阶段策划测试：角色设计 / 主题定调 / save-plan。

覆盖：
- plan-characters 端点：AI 产出角色档案，存入 plan_characters
- plan-theme 端点：前置校验（需先有大纲），AI 产出主题
- save-plan 端点：保存编辑后的策划内容，校验字段白名单
- 无灵感输入时返回 400
"""
import pytest
from unittest.mock import patch
from app import create_app, db
from app.models import ShortStory


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        max_id = db.session.query(db.func.max(ShortStory.id)).scalar() or 0
        yield app
        ShortStory.query.filter(ShortStory.id > max_id).delete(synchronize_session=False)
        db.session.commit()


def _make_story(**kwargs):
    defaults = dict(title="测试短篇", mode="inspiration", inspiration="一个复仇故事",
                    word_target=3000)
    defaults.update(kwargs)
    s = ShortStory(**defaults)
    db.session.add(s)
    db.session.commit()
    return s


class TestPlanCharacters:
    def test_generate_characters(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        with patch("app.routes.short_story.generate._call_ai_sync_wrapper",
                    return_value="## 主要角色\n### 主角\n- 身份：测试"):
            r = client.post(f"/short/{s.id}/plan-characters")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert "主角" in data["plan_characters"]
        # 验证持久化
        s2 = db.session.get(ShortStory, s.id)
        assert "主角" in s2.plan_characters

    def test_no_inspiration_returns_400(self, app_ctx):
        s = _make_story(inspiration="", theme="")
        client = app_ctx.test_client()
        r = client.post(f"/short/{s.id}/plan-characters")
        assert r.status_code == 400

    def test_llm_error_returns_502(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        from app.services.llm import LLMError
        with patch("app.routes.short_story.generate._call_ai_sync_wrapper",
                    side_effect=LLMError("API 401")):
            r = client.post(f"/short/{s.id}/plan-characters")
        assert r.status_code == 502


class TestPlanTheme:
    def test_requires_concept(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        r = client.post(f"/short/{s.id}/plan-theme")
        assert r.status_code == 400

    def test_generate_theme(self, app_ctx):
        s = _make_story()
        s.concept = "【核心概念】复仇与放下"
        db.session.commit()
        client = app_ctx.test_client()
        with patch("app.routes.short_story.generate._call_ai_sync_wrapper",
                    return_value="## 核心主题\n复仇的代价"):
            r = client.post(f"/short/{s.id}/plan-theme")
        assert r.status_code == 200
        data = r.get_json()
        assert "复仇" in data["plan_theme"]


class TestSavePlan:
    def test_save_characters(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        r = client.post(f"/short/{s.id}/save-plan",
                        data={"field": "plan_characters", "content": "编辑后的角色"})
        assert r.status_code == 200
        assert db.session.get(ShortStory, s.id).plan_characters == "编辑后的角色"

    def test_save_theme(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        r = client.post(f"/short/{s.id}/save-plan",
                        data={"field": "plan_theme", "content": "编辑后的主题"})
        assert r.status_code == 200
        assert db.session.get(ShortStory, s.id).plan_theme == "编辑后的主题"

    def test_invalid_field_rejected(self, app_ctx):
        s = _make_story()
        client = app_ctx.test_client()
        r = client.post(f"/short/{s.id}/save-plan",
                        data={"field": "content", "content": "恶意写入"})
        assert r.status_code == 400
