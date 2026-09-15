"""生成文本 vs 对标书的雷同检测(P0 生成期差异化,零 LLM,advisory)。

双指标(调研:知网 13 字红线 + containment 方向性):
- 情节骨架雷同:生成章 vs 对标书**逐章摘要**的 8-gram containment
  (containment = |G∩R|/|G|,非对称——"短文档抄进长文档"必须用生成侧做分母)
- 文句抄袭红线:连续 ≥13 字相同即命中(知网标准;≥20 字升级高危)

阈值(可按自有数据标定):containment <0.10 通过 / 0.10-0.18 提示 / >0.18 或
存在红线命中 → 建议重生(带整改清单)。advisory 只报告,不拦截落库。
"""
import re

REDLINE_N = 13        # 红线:连续 13 字(对齐知网)
HIGH_REDLINE_N = 20   # 高危:连续 20 字
SHINGLE_N = 8         # 8-gram:约 2-3 个词组,兼顾偶然重合率与灵敏度
WARN_CONTAINMENT = 0.10
ALARM_CONTAINMENT = 0.18
_MAX_REDLINES = 5


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def _shingles(text, n=SHINGLE_N):
    t = _norm(text)
    return {t[i:i + n] for i in range(max(len(t) - n + 1, 0))}


def _redline_runs(gen_text, ref_text, n=REDLINE_N, max_runs=_MAX_REDLINES):
    """在 gen_text 中找与 ref_text 连续 ≥n 字相同的片段(合并相邻命中)。

    返回 [{"len": 长度, "quote": 片段(≤50字)}],按长度降序。
    """
    a, b = _norm(gen_text), _norm(ref_text)
    if len(a) < n or len(b) < n:
        return []
    b_subs = {b[i:i + n] for i in range(len(b) - n + 1)}
    starts = [i for i in range(len(a) - n + 1) if a[i:i + n] in b_subs]
    if not starts:
        return []
    # 合并连续起点:起点 s..e 连续命中 ⇒ 公共子串长 n+(e-s)
    runs = []
    run_start = prev = starts[0]
    for i in starts[1:]:
        if i == prev + 1:
            prev = i
            continue
        runs.append((run_start, prev))
        run_start = prev = i
    runs.append((run_start, prev))
    out = []
    for s_pos, e_pos in runs:
        length = n + (e_pos - s_pos)
        out.append({"len": length,
                    "quote": a[s_pos:s_pos + min(length, 50)]})
    out.sort(key=lambda r: -r["len"])
    return out[:max_runs]


def check_vs_blueprint(text, ref_summaries):
    """生成章文本 vs 对标书逐章摘要列表。

    返回 None(无对比源)或:
    {"containment": float, "ref_chapter": int, "redlines": [...], "verdict": "pass"|"warn"|"alarm"}
    """
    refs = [_norm(r.get("summary", "")) for r in ref_summaries if isinstance(r, dict)]
    refs = [r for r in refs if len(r) >= SHINGLE_N]
    if not refs:
        return None
    g = _shingles(text)
    if not g:
        return None
    contain_max, best = 0.0, 0
    for i, r in enumerate(refs, start=1):
        inter = len(g & _shingles(r))
        c = inter / len(g)
        if c > contain_max:
            contain_max, best = c, i
    redlines = []
    for i, r in enumerate(refs, start=1):
        for run in _redline_runs(text, r):
            run["ref_chapter"] = i
            redlines.append(run)
    redlines.sort(key=lambda r: -r["len"])
    redlines = redlines[:_MAX_REDLINES]
    has_high = any(r["len"] >= HIGH_REDLINE_N for r in redlines)
    if contain_max > ALARM_CONTAINMENT or has_high:
        verdict = "alarm"
    elif contain_max >= WARN_CONTAINMENT or redlines:
        verdict = "warn"
    else:
        verdict = "pass"
    return {"containment": round(contain_max, 3), "ref_chapter": best or None,
            "redlines": redlines, "verdict": verdict}


def blueprint_ref_summaries(task):
    """从拆书任务的逐章摘要取对比源(原文视角,仅供雷同检测——不进生成上下文)。"""
    import json as _json
    try:
        summaries = _json.loads(task.chapters_summary_json or "[]")
    except (_json.JSONDecodeError, TypeError):
        summaries = []
    return summaries if isinstance(summaries, list) else []


def check_chapter_vs_blueprint(task_id, text):
    """便捷入口:按拆书任务检测生成章节。

    快路(短书无摘要):用 source_text 全文做对比源(写手复审修复:
    短书没有逐章摘要,不能静默跳过雷同检测)。
    """
    from app.models import db, PlagiarizeTask
    task = db.session.get(PlagiarizeTask, task_id)
    if not task:
        return None
    refs = blueprint_ref_summaries(task)
    if refs:
        return check_vs_blueprint(text, refs)
    # 快路回退:无摘要时直接用 source_text(短书原文全文)
    if task.source_text and len(task.source_text.strip()) >= SHINGLE_N:
        return check_vs_blueprint(text, [{"summary": task.source_text}])
    return None


def check_self_repetition(novel_id, chapter_number, text, lookback=2):
    """自查:生成章 vs 自己前 N 章的 13 字连续重合(advisory,防自身套路化)。"""
    from app.models import Chapter, ChapterVersion
    refs = []
    for ch in Chapter.query.filter(
            Chapter.novel_id == novel_id,
            Chapter.chapter_number < chapter_number,
    ).order_by(Chapter.chapter_number.desc()).limit(lookback).all():
        ver = ChapterVersion.query.filter_by(chapter_id=ch.id).order_by(
            ChapterVersion.version_number.desc()).first()
        if ver and (ver.content or "").strip():
            refs.append({"ref_chapter": ch.chapter_number, "summary": ver.content})
    if not refs:
        return None
    return check_vs_blueprint(text, refs)
