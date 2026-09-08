"""困惑度雷达 — 逐 token 对数概率定位「过于顺滑」的句子。

原理：朱雀第一维检测信号是困惑度（AI 选词永远是最优解，"太顺了"）。
ai_metric 的 11 项构式特征管不到选词分布层；本模块用厂商 logprobs 把
逐 token 概率拿回来，按句聚合困惑度（ppl = exp(-平均对数概率)），
找出全文最可预测的句子作为定向改写目标——补上「选词层」雷达。

实现方式（chat API 限制）：Chat Completions 只能拿到*生成*token 的
logprobs，因此让模型 temperature=0 逐字复述目标文本，复述 token 的
对数概率即模型对该文本可预测性的估计。对齐采用带跳前重同步的顺序
匹配，复述覆盖率 <70% 的分块标记未对齐并跳过，不污染统计。

降级纪律：厂商不支持 logprobs / 全部分块失败 → {"available": False}，
功能隐身，绝不阻断主链路。计分配置复用 summary Agent（诊断走便宜模型）。

阈值现状：smooth_ratio 的 0.6×中位数线是拍脑袋初值，与朱雀分的相关性
待校准（同 ai_metric 统计指标的处置）——先给排序与摘录，阈值后置。
"""
import logging
import math
from bisect import bisect_right

from app.services.ai_metric import _split_sentences
from app.services.llm import call_llm_with_logprobs, LLMError

logger = logging.getLogger(__name__)

_ECHO_PROMPT = (
    "请逐字复述下面的文本。要求：一个字都不能改动，不要增删任何文字或标点，"
    "不要加引号、说明或任何额外内容，直接原样输出。\n\n{text}"
)

_MIN_ALIGN_COVERAGE = 0.7   # 复述覆盖率低于此值的分块判为未对齐
_MIN_SENTENCE_TOKENS = 3    # 少于 3 个 token 的句子统计不稳，不计分
_SMOOTH_RATIO_LINE = 0.6    # ppl < 0.6×全文中位数 视为「过于顺滑」（待校准）


def _split_sentences_with_offsets(text):
    """切句并保留原文偏移：[(start, end, sentence), ...]，供跨分块定位。"""
    result = []
    pos = 0
    for s in _split_sentences(text):
        start = text.find(s, pos)
        if start < 0:  # find 失败兜底（理论上不会：顺序切片）
            start = pos
        result.append((start, start + len(s), s))
        pos = start + len(s)
    return result


def _chunk_sentences(offset_sentences, max_chars):
    """按原文偏移把句子打包成 ≤max_chars 的复述分块。"""
    chunks = []
    cur, cur_start = [], None
    for start, end, s in offset_sentences:
        if cur and (end - cur_start) > max_chars:
            chunks.append(cur)
            cur = []
        if not cur:
            cur_start = start
        cur.append((start, end, s))
    if cur:
        chunks.append(cur)
    return chunks


def _align_echo(chunk_text, tokens):
    """把复述 token 流对齐回分块文本。

    返回 ([(norm_pos, logprob), ...], coverage)。空白跳过不参与对齐；
    顺序匹配失配时向源串前方跳 8 字符重同步（模型吞字/改字容忍），
    找不到则丢弃该字符（模型前言/幻觉不污染统计）。
    """
    norm_chars, mapping = [], []
    for i, ch in enumerate(chunk_text):
        if not ch.isspace():
            norm_chars.append(ch)
            mapping.append(i)
    norm = "".join(norm_chars)

    aligned, pos, matched = [], 0, 0
    for tok, lp in tokens:
        for ch in tok:
            if ch.isspace():
                continue
            if pos < len(norm) and ch == norm[pos]:
                aligned.append((pos, lp))
                pos += 1
                matched += 1
                continue
            found = -1
            for j in range(pos + 1, min(pos + 8, len(norm))):
                if norm[j] == ch:
                    found = j
                    break
            if found >= 0:      # 源串片段被吞/改：推进但不记概率
                pos = found + 1
                matched = 0
            else:               # 源串外内容：丢弃
                matched = 0
    coverage = (len({p for p, _ in aligned}) / len(norm)) if norm else 0.0
    return aligned, coverage, mapping


def _score_chunk(chunk_text, cfg):
    """复述一个分块，返回按分块内偏移对齐的 [(orig_offset, logprob)]。

    Raises:
        LLMError: 厂商调用失败或不支持 logprobs。
        ValueError: 复述覆盖率不足（文本未被忠实复述）。
    """
    text, tokens = call_llm_with_logprobs(
        model=cfg["model_name"], messages=[
            {"role": "user", "content": _ECHO_PROMPT.format(text=chunk_text)},
        ],
        api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
        provider_type=cfg.get("provider_type", "deepseek"),
        temperature=0.0, max_tokens=len(chunk_text) * 2 + 64,
    )
    logger.debug("radar echo %d chars -> %d chars", len(chunk_text), len(text))
    aligned, coverage, mapping = _align_echo(chunk_text, tokens)
    if coverage < _MIN_ALIGN_COVERAGE:
        raise ValueError(f"复述覆盖率不足({coverage:.0%})")
    return [(mapping[p], lp) for p, lp in aligned]


def analyze_perplexity(text, cfg, max_chunk_chars=700):
    """逐句困惑度分析。cfg 为 effective config 形状（model_name/api_key/...）。

    Returns:
        {"available": True, "overall_ppl", "median_ppl", "scored_count",
         "smooth_ratio", "smoothest": [{ppl, excerpt, chars}], ...}
        或 {"available": False, "reason": str}。
    """
    text = (text or "").strip()
    if len(text) < 60:
        return {"available": False, "reason": "文本太短，不足以统计逐句困惑度"}

    offset_sentences = _split_sentences_with_offsets(text)
    chunks = _chunk_sentences(offset_sentences, max_chunk_chars)

    # 聚合到句：sum(logprob) 与 token 数按句累加（跨分块保持偏移一致）
    sent_stats = {}  # start -> [sum_lp, n_tokens, sentence]
    chunk_notes = []
    ok_chunks = 0
    last_error = None
    for group in chunks:
        chunk_text = text[group[0][0]:group[-1][1]]
        try:
            aligned = _score_chunk(chunk_text, cfg)
        except LLMError as e:
            last_error = str(e)
            chunk_notes.append(f"分块调用失败：{chunk_text[:20]}…")
            continue
        except ValueError as e:
            chunk_notes.append(f"分块未对齐（{e}）：{chunk_text[:20]}…")
            continue
        ok_chunks += 1
        base = group[0][0]
        starts = [s for s, _, _ in group]
        for offset, lp in aligned:
            idx = bisect_right(starts, base + offset) - 1
            start, _, sentence = group[idx]
            st = sent_stats.setdefault(start, [0.0, 0, sentence])
            st[0] += lp
            st[1] += 1

    if ok_chunks == 0:
        reason = last_error or "全部分块未能对齐（复述失真）"
        return {"available": False, "reason": reason}

    scored = []
    for start, (sum_lp, n, sentence) in sorted(sent_stats.items()):
        if n >= _MIN_SENTENCE_TOKENS:
            scored.append({"ppl": math.exp(-sum_lp / n), "tokens": n,
                           "excerpt": sentence.strip()[:50], "start": start})
    if not scored:
        return {"available": False, "reason": "对齐后无足够 token 的句子"}

    ppls = sorted(s["ppl"] for s in scored)
    total_lp = sum(math.log(s["ppl"]) * s["tokens"] for s in scored)
    total_n = sum(s["tokens"] for s in scored)
    median = ppls[len(ppls) // 2]
    line = median * _SMOOTH_RATIO_LINE
    smooth = [s for s in scored if s["ppl"] < line]
    top_n = max(3, round(len(scored) * 0.15))
    smoothest = sorted(scored, key=lambda s: s["ppl"])[:top_n]

    return {
        "available": True,
        "overall_ppl": round(math.exp(-total_lp / total_n), 2),
        "median_ppl": round(median, 2),
        "scored_count": len(scored),
        "smooth_line": round(line, 2),
        "smooth_ratio": round(len(smooth) / len(scored), 3),
        "smoothest": [
            {"ppl": round(s["ppl"], 2), "excerpt": s["excerpt"]}
            for s in smoothest
        ],
        "unaligned_notes": chunk_notes,
    }


def format_radar_report(report):
    """把雷达报告渲染为人类可读文本块（gate 报告 / 定向改写指令共用）。"""
    if not report.get("available"):
        return f"困惑度雷达不可用：{report.get('reason', '未知原因')}"
    lines = [
        f"全文困惑度 {report['overall_ppl']}（句中位数 {report['median_ppl']}），"
        f"过于顺滑句占比 {report['smooth_ratio']:.0%}"
        f"（低于 {report['smooth_line']} 计入）",
        "最「可预测」的句子（定向改写目标，选词太在模型舒适区内）：",
    ]
    for s in report["smoothest"]:
        lines.append(f"  [ppl {s['ppl']}] {s['excerpt']}")
    for note in report.get("unaligned_notes", []):
        lines.append(f"  ⚠ {note}")
    return "\n".join(lines)
