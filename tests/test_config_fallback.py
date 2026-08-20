"""配置解析优先级测试。

覆盖：
- get_auto_default_model 按 Agent 分组智能选择（fast/deep 关键词）
- get_model_config 厂商自动默认（无需 Per-Agent 手动配置）
- 显式 llm_model 覆盖自动默认
- 模型取消勾选后自动回退
- get_effective_config 三层优先级（Agent 层只覆盖显式键）
"""
from types import SimpleNamespace

import pytest
from app import create_app, db
from app.models import Setting
from app.models.llm_provider import LLMProvider, LLMModel
from app.config_utils import (
    get_model_config, get_effective_config, get_auto_default_model, _reset_provider_cache,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        # 快照现有数据，测试后恢复
        old_providers = {p.id: p.enabled for p in LLMProvider.query.all()}
        old_settings = {s.key: s.value for s in Setting.query.all()}
        max_pid = db.session.query(db.func.max(LLMProvider.id)).scalar() or 0
        max_mid = db.session.query(db.func.max(LLMModel.id)).scalar() or 0

        # 屏蔽现有厂商，保证自动默认只命中测试创建的厂商
        LLMProvider.query.filter(LLMProvider.id <= max_pid).update(
            {"enabled": False}, synchronize_session=False)
        db.session.commit()
        _reset_provider_cache()

        yield app

        # 清理测试新增数据 + 恢复原有数据
        LLMModel.query.filter(LLMModel.id > max_mid).delete(synchronize_session=False)
        LLMProvider.query.filter(LLMProvider.id > max_pid).delete(synchronize_session=False)
        for s in Setting.query.all():
            if s.key in old_settings:
                s.value = old_settings[s.key]
            else:
                db.session.delete(s)
        for k, v in old_settings.items():
            if not Setting.query.get(k):
                db.session.add(Setting(key=k, value=v))
        for p in LLMProvider.query.filter(LLMProvider.id <= max_pid).all():
            p.enabled = old_providers[p.id]
        db.session.commit()
        _reset_provider_cache()


def _make_provider(name="DeepSeek", key="sk-new-valid-key", enabled=True):
    p = LLMProvider(name=name, provider_type="deepseek",
                    base_url="https://api.deepseek.com", api_key=key, enabled=enabled)
    db.session.add(p)
    db.session.commit()
    return p


def _make_model(provider_id, model_id, enabled=True):
    m = LLMModel(provider_id=provider_id, model_id=model_id,
                 display_name=model_id, enabled=enabled)
    db.session.add(m)
    db.session.commit()
    return m


def _save_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = value
    else:
        db.session.add(Setting(key=key, value=value))
    db.session.commit()


def _del_setting(key):
    s = Setting.query.get(key)
    if s:
        db.session.delete(s)
        db.session.commit()


class TestAutoDefault:
    def test_fast_agent_picks_flash_model(self, app_ctx):
        p = _make_provider()
        _make_model(p.id, "deepseek-v4-pro")   # id 更小，但不含 fast 关键词
        _make_model(p.id, "deepseek-v4-flash")
        _reset_provider_cache()
        auto = get_auto_default_model("writer")
        assert auto["model_name"] == "deepseek-v4-flash"
        assert auto["api_key"] == "sk-new-valid-key"

    def test_deep_agent_picks_pro_model(self, app_ctx):
        p = _make_provider()
        _make_model(p.id, "deepseek-v4-flash")  # id 更小，但不含 pro 关键词
        _make_model(p.id, "deepseek-v4-pro")
        _reset_provider_cache()
        auto = get_auto_default_model("critic")
        assert auto["model_name"] == "deepseek-v4-pro"

    def test_no_keyword_match_falls_to_first(self, app_ctx):
        p = _make_provider()
        _make_model(p.id, "some-model-x")
        _make_model(p.id, "another-model-y")
        _reset_provider_cache()
        auto = get_auto_default_model("writer")
        assert auto["model_name"] == "some-model-x"

    def test_disabled_provider_skipped(self, app_ctx):
        _make_provider(name="Disabled", key="sk-disabled", enabled=False)
        p2 = _make_provider(name="Active", key="sk-active")
        _make_model(p2.id, "deepseek-v4-pro")
        _reset_provider_cache()
        auto = get_auto_default_model("critic")
        assert auto["api_key"] == "sk-active"

    def test_no_provider_returns_none(self, app_ctx):
        _reset_provider_cache()
        assert get_auto_default_model("writer") is None


class TestModelConfigFallback:
    def test_provider_used_without_per_agent_config(self, app_ctx):
        """厂商配好后，无需 Per-Agent 配置即自动生效（修复 401 场景）。"""
        _del_setting("api_key")
        _del_setting("base_url")
        _del_setting("model_name")
        p = _make_provider(key="sk-auto-key")
        _make_model(p.id, "deepseek-v4-flash")
        _make_model(p.id, "deepseek-v4-pro")
        _reset_provider_cache()

        cfg = get_model_config("short_story")
        assert cfg["api_key"] == "sk-auto-key"
        assert cfg["base_url"] == "https://api.deepseek.com"
        assert cfg["model_name"] == "deepseek-v4-flash"  # short_story 属 fast 组

        cfg2 = get_model_config("audit")
        assert cfg2["model_name"] == "deepseek-v4-pro"   # audit 属 deep 组

    def test_explicit_llm_model_overrides_auto(self, app_ctx):
        p = _make_provider()
        flash = _make_model(p.id, "deepseek-v4-flash")
        _make_model(p.id, "deepseek-v4-pro")
        _save_setting("llm_model_writer", f"{p.id}:{flash.model_id}")
        _reset_provider_cache()

        cfg = get_model_config("writer")
        assert cfg["model_name"] == "deepseek-v4-flash"  # 显式选择 flash

    def test_unchecked_model_falls_back_to_auto(self, app_ctx):
        """Per-Agent 指定的模型被取消勾选后，自动回退默认而非报错。"""
        p = _make_provider()
        target = _make_model(p.id, "deepseek-v4-pro")
        _make_model(p.id, "deepseek-v4-flash")
        _save_setting("llm_model_critic", f"{p.id}:{target.model_id}")
        _reset_provider_cache()

        # 取消勾选
        target.enabled = False
        db.session.commit()
        _reset_provider_cache()

        cfg = get_model_config("critic")
        assert cfg["model_name"] == "deepseek-v4-flash"  # 回退到唯一可用模型

    def test_agent_params_still_apply_with_auto(self, app_ctx):
        p = _make_provider()
        _make_model(p.id, "deepseek-v4-flash")
        _save_setting("temperature_writer", "0.5")
        _save_setting("max_tokens_writer", "2048")
        _reset_provider_cache()

        cfg = get_model_config("writer")
        assert cfg["model_name"] == "deepseek-v4-flash"
        assert cfg["temperature"] == 0.5
        assert cfg["max_tokens"] == 2048

    def test_legacy_model_name_ignored_when_auto_exists(self, app_ctx):
        """存在自动默认时，裸 model_name 覆盖被忽略（避免模型名与 key 错配 401）。"""
        p = _make_provider()
        _make_model(p.id, "deepseek-v4-flash")
        _save_setting("model_name_writer", "some-other-model")
        _reset_provider_cache()

        cfg = get_model_config("writer")
        assert cfg["model_name"] == "deepseek-v4-flash"

    def test_legacy_model_name_used_without_provider(self, app_ctx):
        """无厂商配置时，旧文本输入的 model_name 覆盖仍生效。"""
        _save_setting("model_name_writer", "legacy-model-x")
        _reset_provider_cache()

        cfg = get_model_config("writer")
        assert cfg["model_name"] == "legacy-model-x"


class TestEffectiveConfigLayers:
    def test_novel_override_survives_unconfigured_agent(self, app_ctx):
        """Agent 无显式配置时，不应冲掉 novel.model_override 的 api_key。"""
        p = _make_provider(key="sk-auto")
        _make_model(p.id, "deepseek-v4-pro")
        _reset_provider_cache()

        novel = SimpleNamespace(
            model_override='{"api_key": "sk-novel-key", "model_name": "custom-x"}')
        cfg = get_effective_config(novel, agent_type="critic")
        assert cfg["api_key"] == "sk-novel-key"
        assert cfg["model_name"] == "custom-x"

    def test_agent_llm_model_overrides_novel(self, app_ctx):
        p = _make_provider(key="sk-auto")
        m = _make_model(p.id, "deepseek-v4-pro")
        _save_setting("llm_model_critic", f"{p.id}:{m.model_id}")
        _reset_provider_cache()

        novel = SimpleNamespace(model_override='{"api_key": "sk-novel-key"}')
        cfg = get_effective_config(novel, agent_type="critic")
        assert cfg["api_key"] == "sk-auto"   # Agent 显式 > novel 覆盖
        assert cfg["model_name"] == "deepseek-v4-pro"
