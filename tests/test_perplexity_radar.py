"""困惑度雷达测试：对齐算法、逐句 ppl 聚合、降级纪律、gate-check 接入。"""
import math

from app.services import perplexity_radar as radar
from app.services.llm import LLMError


def _make_text():
    """smooth/rough 句交替 ×9 = 18 句（过 60 字门槛），smooth 句人为「更可预测」。"""
    smooth = "他在桌边坐了很久没有说话。"
    rough = "雨点砸在铁皮棚顶噼里啪啦乱成一片麻。"
    sentences = []
    for i in range(9):
        sentences += [smooth, rough]
    return "".join(sentences), smooth, rough


def _fake_echo(lp_smooth=-0.1, lp_rough=-2.0):
    """复述伪对象：按句切 2 字 token；smooth 句 logprob 高（可预测）。"""

    def fake(model, messages, **kw):
        chunk = messages[0]["content"].split("\n\n", 1)[1]
        smooth = _make_text()[1]
        tokens = []
        for _, _, s in radar._split_sentences_with_offsets(chunk):
            lp = lp_smooth if s == smooth else lp_rough
            norm = "".join(ch for ch in s if not ch.isspace())
            for i in range(0, len(norm) - 1, 2):
                tokens.append((norm[i:i + 2], lp))
        return chunk, tokens

    return fake


def test_split_sentences_with_offsets():
    text = "第一句在这里。第二句跟在后面！"
    parts = radar._split_sentences_with_offsets(text)
    assert [p[2] for p in parts] == ["第一句在这里。", "第二句跟在后面！"]
    for start, end, s in parts:
        assert text[start:end] == s


def test_align_echo_full_and_junk():
    chunk = "他坐在桌边，很久没有说话。"
    norm = "".join(ch for ch in chunk if not ch.isspace())
    # 完美复述：2 字 token
    tokens = [(norm[i:i + 2], -0.3) for i in range(0, len(norm), 2)]
    aligned, coverage, mapping = radar._align_echo(chunk, tokens)
    assert coverage == 1.0
    assert len(aligned) == len(norm)
    assert mapping[aligned[0][0]] == 0  # 首对齐位映射回原文起始

    # 前言 + 幻觉尾巴：源串外内容被丢弃，不产生错误对齐
    tokens_junk = [("当然", -0.5)] + tokens + [("以上", -0.5)]
    aligned2, cov2, _ = radar._align_echo(chunk, tokens_junk)
    assert cov2 == 1.0
    assert len(aligned2) == len(aligned)


def test_align_echo_tolerates_dropped_chars():
    chunk = "铁皮棚顶噼里啪啦乱成一团。"
    norm = "".join(ch for ch in chunk if not ch.isspace())
    # 复述吞掉了「噼里」：顺序失配走跳前重同步，覆盖率仍达标
    broken = norm.replace("噼里", "")
    tokens = [(broken[i:i + 2], -0.4) for i in range(0, len(broken), 2)]
    aligned, coverage, _ = radar._align_echo(chunk, tokens)
    assert coverage >= radar._MIN_ALIGN_COVERAGE


def test_analyze_perplexity_ranks_smooth_sentences(app, monkeypatch):
    text, smooth, rough = _make_text()
    monkeypatch.setattr(radar, "call_llm_with_logprobs", _fake_echo())

    cfg = {"model_name": "m", "api_key": "k", "base_url": "", "provider_type": "deepseek"}
    rep = radar.analyze_perplexity(text, cfg)

    assert rep["available"] is True
    assert rep["scored_count"] == 18
    # smooth 句 ppl = e^0.1 ≈ 1.11，rough 句 ppl = e^2.0 ≈ 7.39
    smooth_ppl = math.exp(0.1)
    assert all(abs(s["ppl"] - smooth_ppl) < 0.01 for s in rep["smoothest"])
    assert all(smooth in s["excerpt"] for s in rep["smoothest"])
    assert rough not in rep["smoothest"][0]["excerpt"]
    assert rep["smooth_ratio"] > 0.4  # 约一半句子低于 0.6×中位数线


def test_analyze_perplexity_too_short(app):
    rep = radar.analyze_perplexity("太短了", {"model_name": "m"})
    assert rep == {"available": False, "reason": "文本太短，不足以统计逐句困惑度"}


def test_analyze_perplexity_provider_failure(app, monkeypatch):
    def boom(model, messages, **kw):
        raise LLMError("厂商未返回 logprobs（可能不支持该参数）")

    monkeypatch.setattr(radar, "call_llm_with_logprobs", boom)
    text, _, _ = _make_text()
    rep = radar.analyze_perplexity(text, {"model_name": "m"})
    assert rep["available"] is False
    assert "logprobs" in rep["reason"]


def test_analyze_perplexity_unaligned_chunk_degrades(app, monkeypatch):
    """复述完全失真：分块标记未对齐，不产伪统计。"""
    def garbage(model, messages, **kw):
        junk = "这是一段与原文毫无关系的回复内容呀。"
        return junk, [(junk[i:i + 2], -0.5) for i in range(0, len(junk) - 1, 2)]

    monkeypatch.setattr(radar, "call_llm_with_logprobs", garbage)
    text, _, _ = _make_text()
    rep = radar.analyze_perplexity(text, {"model_name": "m"})
    assert rep["available"] is False
    assert "对齐" in rep["reason"] or "复述" in rep["reason"]


def test_format_radar_report():
    smooth = "他在桌边坐了很久没有说话。"
    rep = {
        "available": True, "overall_ppl": 1.5, "median_ppl": 1.2,
        "smooth_line": 0.72, "smooth_ratio": 0.2,
        "smoothest": [{"ppl": 0.5, "excerpt": smooth}],
        "unaligned_notes": ["分块未对齐（复述覆盖率不足(60%)）：某某…"],
    }
    out = radar.format_radar_report(rep)
    assert "过于顺滑句占比 20%" in out
    assert smooth in out
    assert "未对齐" in out

    out2 = radar.format_radar_report({"available": False, "reason": "厂商不支持"})
    assert "困惑度雷达不可用" in out2 and "厂商不支持" in out2


def test_gate_check_with_ppl_opt_in(app, client, monkeypatch):
    text, _, _ = _make_text()
    sentinel = {"available": True, "overall_ppl": 1.0, "median_ppl": 1.0,
                "smooth_line": 0.6, "smooth_ratio": 0.1, "scored_count": 3,
                "smoothest": [], "unaligned_notes": []}
    monkeypatch.setattr(radar, "analyze_perplexity", lambda t, cfg: sentinel)

    resp = client.post("/api/skills/gate-check",
                       json={"text": text, "with_ppl": True})
    assert resp.get_json()["perplexity"] == sentinel

    # 默认关闭：不带 with_ppl 不触发雷达（省 N 次复述调用）
    resp2 = client.post("/api/skills/gate-check", json={"text": text})
    assert "perplexity" not in resp2.get_json()
