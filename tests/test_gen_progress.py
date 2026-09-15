"""生成进度诊断链路测试：阶段事件 / SSE 进度帧 / 共享连接池。

针对「AI 生成本章很慢」的诊断改造——把串行多轮 LLM 调用（大纲→正文→
续写补足）的阶段、首字延迟、耗时透出到 SSE 进度帧，供前端实时展示
「当前阶段/用时/字数/厂商可能繁忙」，并复用 HTTP 连接池省去每轮握手。
"""
import json

from app.services import writer_chain as wc
from app.services.llm import _build_http_client, _HTTP_CLIENT_CACHE


# ---------------------------------------------------------------------------
# generation_tokens 阶段事件
# ---------------------------------------------------------------------------

def _fake_stream(chunks):
    def _gen(*args, **kwargs):
        for c in chunks:
            yield c
    return _gen


def test_generation_tokens_emits_progress_events(monkeypatch):
    # 缩小字数底线逼出续写轮：首轮 3 字 < 底线 5 字 → 触发 1 轮补足
    monkeypatch.setattr(wc, "CHAPTER_WORD_FLOOR", 5)
    calls = {"n": 0}

    def fake_stream(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield from ["正文", "ab"]  # 共 4 字 < 底线 5 字 → 触发续写
        else:
            yield from ["续写", "内容凑够五个字"]

    monkeypatch.setattr(wc, "stream_llm_tokens", fake_stream)
    cfg = {"model_name": "test-model", "provider_type": "deepseek"}

    events = []
    tokens = list(wc.generation_tokens(
        [{"role": "user", "content": "x"}], cfg,
        word_target=50, on_event=events.append))

    full = "".join(tokens)
    assert "正文ab" in full and "续写" in full  # 首轮 + 续写轮都进了正文

    stages = [e["stage"] for e in events]
    assert stages[0] == "round_start"
    assert "continue_start" in stages
    assert stages.count("round_start") == 2      # 首轮 + 续写轮
    assert stages.count("first_token") == 2
    assert stages.count("round_end") == 2

    first = next(e for e in events if e["stage"] == "first_token")
    assert first["model"] == "test-model"
    assert first["provider"] == "deepseek"
    assert "ttft_s" in first

    cont = next(e for e in events if e["stage"] == "continue_start")
    assert cont["round"] == 2
    assert cont["floor"] == 5
    assert cont["current_chars"] == len("正文ab")

    ends = [e for e in events if e["stage"] == "round_end"]
    for e in ends:
        assert "chars" in e and "elapsed_s" in e


def test_generation_tokens_survives_callback_errors(monkeypatch):
    """on_event 抛异常绝不影响生成主链路。"""
    monkeypatch.setattr(wc, "stream_llm_tokens", _fake_stream(["你好", "世界"]))

    def bad_on_event(ev):
        raise RuntimeError("回调故障")

    tokens = list(wc.generation_tokens(
        [{"role": "user", "content": "x"}], {"model_name": "m"},
        on_event=bad_on_event))
    assert "".join(tokens) == "你好世界"


def test_generation_tokens_no_callback_still_works(monkeypatch):
    """不传 on_event（编排器/旧调用方）行为不变。"""
    monkeypatch.setattr(wc, "stream_llm_tokens", _fake_stream(["abc"]))
    out = wc.collect_full_text([{"role": "user", "content": "x"}],
                               {"model_name": "m"})
    assert out == "abc"


# ---------------------------------------------------------------------------
# SSE 进度帧（旧客户端只认 token/error/done，未知帧自动忽略 → 向后兼容）
# ---------------------------------------------------------------------------

def test_stream_to_sse_emits_status_frames(monkeypatch):
    from app.routes import generate as gen_mod

    def fake_generation_tokens(messages, cfg, word_target=None, on_event=None):
        on_event({"stage": "round_start", "round": 1})
        on_event({"stage": "first_token", "round": 1, "ttft_s": 2.1,
                  "model": "m1", "provider": "deepseek"})
        yield "你好"
        on_event({"stage": "round_end", "round": 1, "chars": 2, "elapsed_s": 2.5})

    monkeypatch.setattr(gen_mod, "generation_tokens", fake_generation_tokens)
    cfg = {"model_name": "m1", "provider_type": "deepseek"}

    raw = "".join(gen_mod._stream_to_sse(
        [{"role": "user", "content": "x"}], cfg, phase="write"))

    frames = []
    for line in raw.split("\n"):
        if line.startswith("data: "):
            frames.append(json.loads(line[6:]))

    statuses = [f["status"] for f in frames if "status" in f]
    assert statuses[0]["stage"] == "stream_start"
    assert statuses[0]["phase"] == "write"
    assert any(s["stage"] == "first_token" and s["ttft_s"] == 2.1 for s in statuses)

    # 进度帧在对应 token 帧之前（先冲 pending 再吐 token）
    first_token_idx = next(i for i, f in enumerate(frames) if "token" in f)
    first_ft_idx = next(i for i, f in enumerate(frames)
                        if "status" in f and f["status"]["stage"] == "first_token")
    assert first_ft_idx < first_token_idx

    done = next(f for f in frames if f.get("done"))
    assert done["full_text"] == "你好"
    assert "elapsed_s" in done


def test_stream_to_sse_error_still_carries_full_text(monkeypatch):
    from app.routes import generate as gen_mod

    def boom(messages, cfg, word_target=None, on_event=None):
        on_event({"stage": "round_start", "round": 1})
        yield "部分"
        raise wc.LLMError("厂商 429")

    monkeypatch.setattr(gen_mod, "generation_tokens", boom)
    raw = "".join(gen_mod._stream_to_sse([{"role": "user", "content": "x"}],
                                         {"model_name": "m"}))
    assert '"error": "厂商 429"' in raw
    assert '"full_text": "部分"' in raw


# ---------------------------------------------------------------------------
# 共享 HTTP 连接池
# ---------------------------------------------------------------------------

def test_http_client_cache_reuses_client(monkeypatch):
    _HTTP_CLIENT_CACHE.clear()
    try:
        c1 = _build_http_client("https://api.deepseek.com")
        c2 = _build_http_client("https://api.openai.com/v1")
        assert c1 is c2  # 同一校验策略 → 复用同一连接池

        local = _build_http_client("http://127.0.0.1:11434/v1")
        assert local is not c1  # 本机免校验策略 → 独立连接池

        c1.close()
        c3 = _build_http_client("https://api.deepseek.com")
        assert c3 is not c1 and not c3.is_closed  # 被关后自动重建
    finally:
        for c in _HTTP_CLIENT_CACHE.values():
            try:
                c.close()
            except Exception:
                pass
        _HTTP_CLIENT_CACHE.clear()
