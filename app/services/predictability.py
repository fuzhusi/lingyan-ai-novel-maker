"""可预测率测试（100-Endings 的低成本变体，调研 v2 P2-C4）。

原理（学术依据：LLM 的可预测/同质化是对齐训练的系统性偏差；
rubric 评审对「趣味性」盲区最大——前瞻类指标更可信）：
    对「截至第 N-1 章的故事进展」用 fast 模型独立采样 N 次预测
    「下一章会发生的三件事」，计算预测之间的两两重合度。
    重合度越高 = 走向越可预测 = 读者越容易预判 = 平淡风险信号。

定位：诊断工具（advisory），不改稿不阻断。阈值已按书1 24 章回测定标
（P75/P50），跨书定标随 predict-scan 数据积累滚动更新。
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from app.config_utils import get_model_config
from app.services.llm import call_llm_auto, LLMError

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是故事走向预测器。基于已给出的故事进展，预测下一章最可能发生的三件事。"
    "只输出三行，每行一句话，不要编号以外的任何内容。"
)

# 阈值定标：书1《你应该好好爱自己》24 章回测（predict-scan，2026-10-03）
# P50=0.111 / P75=0.124——初值 0.6/0.35 在真实语料上永不触发，已按回测替换。
# 注意：采样温度 0.9 会压低一致性绝对值；换温度需重新定标。
_HIGH = 0.125
_NORMAL = 0.111


def _story_tail(novel_id, before_chapter, tail=3000):
    from app.models import Chapter
    chapters = (Chapter.query
                .filter_by(novel_id=novel_id)
                .filter(Chapter.chapter_number < before_chapter)
                .order_by(Chapter.chapter_number.desc())
                .limit(3).all())
    parts = []
    for ch in reversed(chapters):
        if ch.versions:
            parts.append((ch.versions[-1].content or "")[-tail:])
    return "\n\n".join(parts)


def _shingles(text, k=2):
    text = re.sub(r"\s", "", text)
    return {text[i:i + k] for i in range(len(text) - k + 1)} if len(text) >= k else {text}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_lines(text):
    lines = [re.sub(r"^[\d一二三]+[.、)）]?\s*", "", ln).strip()
             for ln in (text or "").split("\n")]
    return [ln for ln in lines if ln][:3]


def predict_consistency(novel_id, chapter_number, samples=3):
    """返回 {"samples": [[三行预测]...], "consistency": 0-1, "verdict": str,
    "pairwise": [...]}。无前文/调用失败返回 {"error": ...}。"""
    story = _story_tail(novel_id, chapter_number)
    if len(story.strip()) < 500:
        return {"error": "前文正文不足 500 字，无法预测"}
    cfg = get_model_config(agent_type="summary")   # fast 挡
    user = f"【故事进展（末尾部分）】\n{story}\n\n【任务】预测下一章会发生的三件事。"

    def one_run(_idx):
        text = call_llm_auto(
            model=cfg["model_name"],
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": user}],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.9, max_tokens=400,
            timeout=cfg.get("timeout") or 300.0)
        return _parse_lines(text)

    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=samples) as pool:
        futures = [pool.submit(one_run, i) for i in range(samples)]
        for fut in futures:
            try:
                results.append(fut.result())
            except LLMError as e:
                logger.warning("预测采样失败（跳过该样本）: %s", e)
    results = [r for r in results if r]
    if len(results) < 2:
        return {"error": "有效预测样本不足"}
    shingles = [_shingles("".join(r)) for r in results]
    pairwise = []
    for i in range(len(shingles)):
        for j in range(i + 1, len(shingles)):
            pairwise.append(round(_jaccard(shingles[i], shingles[j]), 3))
    consistency = round(sum(pairwise) / len(pairwise), 3) if pairwise else 0.0
    if consistency >= _HIGH:
        verdict = ("高可预测（走向几乎必然）：读者预判成本过低，平淡风险信号——"
                   "下一章大纲里加一个意外变量")
    elif consistency >= _NORMAL:
        verdict = "正常区间"
    else:
        verdict = "新颖性富余（走向难以预判）"
    return {"samples": results, "consistency": consistency,
            "verdict": verdict, "pairwise": pairwise,
            "elapsed": round(time.time() - started, 1)}
