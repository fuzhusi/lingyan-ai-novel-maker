"""国际厂商接入测试：Claude 原生协议分支 / Gemini OpenAI 兼容端点 / 预设表。"""
import pytest

from app.routes.llm_settings import PRESET_PROVIDERS, get_preset_by_type
from app.services import llm as llm_mod
from app.services.llm import (
    LLMError,
    fetch_models_from_provider,
    get_llm,
)


# ---------------------------------------------------------------------------
# 预设表
# ---------------------------------------------------------------------------

def test_preset_providers_contain_international():
    types = [p["type"] for p in PRESET_PROVIDERS]
    assert "anthropic" in types
    assert "gemini" in types
    assert "openai" in types

    anth = get_preset_by_type("anthropic")
    assert anth["base_url"] == "https://api.anthropic.com/v1"
    assert anth["key_url"]  # 前端快速选择要展示取 key 入口

    gem = get_preset_by_type("gemini")
    # Google 官方 OpenAI 兼容端点：无需单独适配即可拉模型/调用
    assert gem["base_url"].endswith("/openai")


# ---------------------------------------------------------------------------
# get_llm 分支
# ---------------------------------------------------------------------------

def test_get_llm_anthropic_uses_native_protocol():
    llm = get_llm("claude-sonnet-4-5", api_key="sk-ant-test",
                  base_url="https://api.anthropic.com/v1",
                  provider_type="anthropic", temperature=0.8, max_tokens=1024)
    from langchain_anthropic import ChatAnthropic
    assert isinstance(llm, ChatAnthropic)
    # 回归锚（评审 P0）：1.7.x 的 ChatAnthropic 没有 http_client 字段，传入会被
    # 转进 model_kwargs 并混入 /v1/messages 请求体（每次调用必失败）
    assert llm.model_kwargs == {}
    payload = llm._get_request_payload([{"role": "user", "content": "hi"}])
    assert "http_client" not in payload
    # 回归锚（评审 P0）：SDK 自行拼接 v1/messages——base_url 带 /v1 时必须归一，
    # 否则拼出 /v1/v1/messages（404）；SDK 要求 base 以 / 结尾
    assert str(llm._client.base_url).endswith("https://api.anthropic.com/")
    assert str(llm._client.base_url) + "v1/messages" == \
        "https://api.anthropic.com/v1/messages"


def test_get_llm_anthropic_logprobs_raises():
    with pytest.raises(LLMError):
        get_llm("claude-sonnet-4-5", api_key="sk-ant-test",
                base_url="https://api.anthropic.com/v1",
                provider_type="anthropic", logprobs=True)


def test_get_llm_gemini_stays_openai_compatible():
    from langchain_openai import ChatOpenAI
    llm = get_llm("gemini-2.5-pro", api_key="g-test",
                  base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                  provider_type="gemini", temperature=0.8, max_tokens=1024)
    assert isinstance(llm, ChatOpenAI)


# ---------------------------------------------------------------------------
# fetch_models_from_provider 认证方式
# ---------------------------------------------------------------------------

class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"id": "claude-sonnet-4-5", "owned_by": "anthropic"}]}


def test_fetch_models_anthropic_uses_native_headers(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _FakeResp()

    monkeypatch.setattr(llm_mod.httpx, "get", fake_get)
    models = fetch_models_from_provider(
        "https://api.anthropic.com/v1", "sk-ant-test", "anthropic")

    assert captured["url"].startswith("https://api.anthropic.com/v1/models")
    assert captured["headers"].get("x-api-key") == "sk-ant-test"
    assert captured["headers"].get("anthropic-version")
    assert "Authorization" not in captured["headers"]
    assert models == [{"id": "claude-sonnet-4-5", "owned_by": "anthropic"}]


def test_fetch_models_openai_still_bearer(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _FakeResp()

    monkeypatch.setattr(llm_mod.httpx, "get", fake_get)
    fetch_models_from_provider("https://api.openai.com/v1", "sk-test", "openai")

    assert captured["headers"].get("Authorization") == "Bearer sk-test"
    assert "x-api-key" not in captured["headers"]
