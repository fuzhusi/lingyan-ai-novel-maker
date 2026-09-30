"""AI_NovelGenerator 源码审核吸收项回归（docs/ai-novelgenerator-adoption.md）。

覆盖：下一章方向注入、大纲节奏回看（激动值曲线/悬念类型/认知过山车）、
<llink>think</think> 思维链剥离（流式跨片）、空产出可重试、custom base_url /v1 归一、
per-agent timeout、近章激动值读取。
"""
import pytest

from app.services.llm import (
    LLMError, _strip_think_stream, get_llm,
)
from app.services.prompt_builder import build_writer_prompt, build_outline_prompt


# ---------------------------------------------------------------------------
# 下一章方向（next-chapter 块）
# ---------------------------------------------------------------------------

def test_writer_prompt_renders_next_chapter_brief():
    msgs = build_writer_prompt(
        novel_title="t", outline="x", next_chapter_brief="主角北上 entering 北境")
    user = msgs[1]["content"]
    assert "下一章方向" in user
    assert "主角北上" in user
    assert "不得提前展开下一章" in user


def test_writer_prompt_no_next_block_when_empty():
    msgs = build_writer_prompt(novel_title="t", outline="x")
    assert "下一章方向" not in msgs[1]["content"]


# ---------------------------------------------------------------------------
# 大纲 prompt：悬念类型词表 + 认知过山车 + 激动值曲线回看
# ---------------------------------------------------------------------------

def test_outline_prompt_suspense_and_pacing():
    msgs = build_outline_prompt(novel_title="t")
    sys_prompt = msgs[0]["content"]
    assert "信息差/道德困境/时间压力" in sys_prompt
    assert "认知过山车" in sys_prompt
    # 曲线是数据，进 user 块而非 system 模板
    assert "激动值曲线" not in sys_prompt


def test_outline_prompt_excitement_curve_block():
    curve = [{"chapter": 3, "density": 7.2}, {"chapter": 4, "density": 8.1}]
    msgs = build_outline_prompt(novel_title="t", excitement_recent=curve)
    user = msgs[1]["content"]
    assert "近章激动值曲线" in user
    assert "第3章 7.2" in user and "第4章 8.1" in user


# ---------------------------------------------------------------------------
# <think> 流式剥离
# ---------------------------------------------------------------------------

def test_strip_think_stream_complete_and_split():
    toks = ["你好", "<th", "ink>秘密推理", "</think>", "世界"]
    assert "".join(_strip_think_stream(toks)) == "你好世界"


def test_strip_think_stream_passthrough_and_unclosed():
    assert "".join(_strip_think_stream(["普通", "文本"])) == "普通文本"
    # 未闭合的 <think>：之后全部抑制
    assert "".join(_strip_think_stream(["a", "<think>", "b", "c"])) == "a"


# ---------------------------------------------------------------------------
# 空产出可重试
# ---------------------------------------------------------------------------

def test_sync_empty_output_retries_then_succeeds(monkeypatch):
    import app.services.llm as m
    calls = {"n": 0}

    def fake_once(**kwargs):
        calls["n"] += 1
        return "" if calls["n"] == 1 else "正文内容"

    monkeypatch.setattr(m, "_call_llm_sync_once", fake_once)
    monkeypatch.setattr(m, "_record_llm_call", lambda *a, **k: None)
    out = m.call_llm_sync(model="t", messages=[{"role": "user", "content": "x"}])
    assert out == "正文内容"
    assert calls["n"] == 2  # 第一次空产出触发重试


def test_sync_empty_output_exhausts_retries(monkeypatch):
    import app.services.llm as m
    monkeypatch.setattr(m, "_call_llm_sync_once", lambda **k: "")
    monkeypatch.setattr(m, "_record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    with pytest.raises(LLMError, match="empty output"):
        m.call_llm_sync(model="t", messages=[{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------
# custom base_url /v1 归一（# 逃逸）
# ---------------------------------------------------------------------------

def test_get_llm_custom_base_url_appends_v1(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.services.llm.ChatOpenAI",
                        lambda **kw: captured.update(kw) or object())
    monkeypatch.setattr("app.services.llm._build_http_client", lambda b: None)
    get_llm(model="m", base_url="https://gw.example.com/api",
            provider_type="custom", api_key="k")
    assert captured["base_url"] == "https://gw.example.com/api/v1"

    captured.clear()
    get_llm(model="m", base_url="https://gw.example.com/v2#",
            provider_type="custom", api_key="k")
    assert captured["base_url"] == "https://gw.example.com/v2"  # # 逃逸

    captured.clear()
    get_llm(model="m", base_url="https://api.deepseek.com",
            provider_type="deepseek", api_key="k")
    # 预设厂商类型不自动补（预设表已带正确路径）
    assert captured["base_url"] == "https://api.deepseek.com"


# ---------------------------------------------------------------------------
# per-agent timeout
# ---------------------------------------------------------------------------

def test_config_utils_timeout_override(app):
    from app import db
    from app.models import Setting
    from app.config_utils import get_effective_config
    with app.app_context():
        # 共享 session 庂跨用例/跨次运行持久：裸 INSERT 二次必炸 UNIQUE，改 upsert
        setting = db.session.get(Setting, "timeout_writer")
        if setting is None:
            setting = Setting(key="timeout_writer", value="600")
            db.session.add(setting)
        else:
            setting.value = "600"
        db.session.commit()
        cfg = get_effective_config(agent_type="writer")
    assert cfg.get("timeout") == 600.0


# ---------------------------------------------------------------------------
# 近章激动值读取
# ---------------------------------------------------------------------------

def test_get_excitement_recent(app):
    import json
    from app import db
    from app.models import Novel, StoryState
    from app.services.prompt_builder.context import get_excitement_recent
    with app.app_context():
        n = Novel(title="曲线书")
        db.session.add(n)
        db.session.commit()
        db.session.add(StoryState(
            novel_id=n.id,
            excitement_history=json.dumps(
                [{"chapter": i, "density": i} for i in range(1, 8)])))
        db.session.commit()
        nid = n.id
    curve = get_excitement_recent(nid, n=5)
    assert len(curve) == 5
    assert curve[0]["chapter"] == 3 and curve[-1]["chapter"] == 7
    assert get_excitement_recent(999999) == []
