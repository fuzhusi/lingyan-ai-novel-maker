"""一致性链（P2）——确定性交叉核对先行，Keepers 复活为「裁决者」。

设计（docs/agent-collaboration.md §3.3）：
    1. 零成本确定性核对把疑点缩到极小集合（时序真相旧值回潮 / 伏笔排期脱班 /
       已回收伏笔复现）；
    2. 疑点才交 LLM 裁决——character_check / lore_check / foreshadow_check
       三个 deep Agent 只回答「这处是否真矛盾、以哪条设定为准」，
       不做全文重读（与休眠 pipeline 的职责有本质区别）；
    3. 裁决结果仍归人工闸门处理（改文 / 改设定 / 忽略）。
"""
import logging

from app.services.chapter_approval import extract_json_dict
from app.services.llm import call_llm_sync, LLMError

logger = logging.getLogger(__name__)

_ADJUDICATE_CAP = 6          # 单次最多送裁决的疑点数（控 token）
_MIN_VALUE_LEN = 2           # 时序真相值参与子串匹配的最小长度
_FACT_SIMILAR_OVERDUE = 10   # 伏笔超过 N 章未提及即列为「推进脱班」疑点

# 疑点类别 → Keepers Agent 类型（复活为裁决者的三个配置）
_KIND_AGENT = {
    "truth_regression": "lore_check",
    "foreshadow_overdue": "foreshadow_check",
    "foreshadow_reappear": "foreshadow_check",
}

_ADJUDICATE_SYSTEM = (
    "你是一致性裁决者。只针对给出的单一疑点，对照设定条目判断它是否构成"
    "真实的叙事矛盾。输出严格 JSON："
    '{"is_conflict": true/false, "reason": "50字以内判定理由", '
    '"suggestion": "一句话处理建议（改文/改设定/可忽略）"}'
    "。不要输出其他内容。拿不准时 is_conflict 给 false。")


def _check_truth_regression(text, novel_id, chapter_number):
    """时序真相旧值回潮：已闭合的旧事实值重新出现在正文中。"""
    suspects = []
    try:
        from app.services.temporal_truth import _get_truths
        truths = _get_truths(novel_id)
    except Exception:
        logger.warning("时序真相读取失败，跳过回潮检查", exc_info=True)
        return suspects
    for t in truths or []:
        old_value = (t.get("value") or "").strip()
        closed_at = t.get("to_chapter")
        # 只看在本章之前已闭合的旧值；值太短/纯数字不参与子串匹配（误报源）
        if not closed_at or closed_at >= chapter_number:
            continue
        if len(old_value) < _MIN_VALUE_LEN or old_value.isdigit():
            continue
        if old_value in text:
            suspects.append({
                "kind": "truth_regression",
                "agent_type": _KIND_AGENT["truth_regression"],
                "title": f"旧设定回潮：{t.get('subject', '?')}·{t.get('property', '?')}",
                "detail": (f"「{old_value}」在第 {closed_at} 章已闭合，"
                            f"但本章正文再次出现。"),
                "excerpt": old_value,
            })
    return suspects


def _check_foreshadow_schedule(text, novel_id, chapter_number):
    """伏笔排期脱班：约定回收章已过 / 长期未推进 / 已回收又复现。"""
    suspects = []
    try:
        from app.models import Foreshadowing
        items = (Foreshadowing.query
                 .filter_by(novel_id=novel_id)
                 .filter(Foreshadowing.status.in_(
                     ["open", "planned", "buried", "advancing",
                      "reclaimable", "resolved"]))
                 .all())
    except Exception:
        logger.warning("伏笔读取失败，跳过排期检查", exc_info=True)
        return suspects
    for f in items:
        if f.status == "resolved":
            # 已回收伏笔的关键词再次出现 → 复现疑点
            title = (f.title or "").strip()
            if len(title) >= 4 and title in text:
                suspects.append({
                    "kind": "foreshadow_reappear",
                    "agent_type": _KIND_AGENT["foreshadow_reappear"],
                    "title": f"已回收伏笔复现：{title}",
                    "detail": f"「{title}」已回收，但本章正文再次出现其关键词。",
                    "excerpt": title,
                })
            continue
        # 活跃伏笔的排期检查
        if (f.resolve_chapter or 0) and f.resolve_chapter <= chapter_number:
            suspects.append({
                "kind": "foreshadow_overdue",
                "agent_type": _KIND_AGENT["foreshadow_overdue"],
                "title": f"回收逾期：{f.title or f'd伏笔#{f.id}'}",
                "detail": (f"约定第 {f.resolve_chapter} 章回收，当前已到"
                            f"第 {chapter_number} 章仍未回收。"),
                "excerpt": (f.description or "")[:80],
            })
        elif (f.last_mentioned_chapter and
              chapter_number - f.last_mentioned_chapter >= max(
                  f.timeout_threshold or 15, _FACT_SIMILAR_OVERDUE)):
            suspects.append({
                "kind": "foreshadow_overdue",
                "agent_type": _KIND_AGENT["foreshadow_overdue"],
                "title": f"推进脱班：{f.title or f'd伏笔#{f.id}'}",
                "detail": (f"第 {f.last_mentioned_chapter} 章后长期未提及"
                            f"（已隔 {chapter_number - f.last_mentioned_chapter} 章）。"),
                "excerpt": (f.description or "")[:80],
            })
    return suspects


def run_deterministic_checks(text, novel_id, chapter_number):
    """零成本确定性核对，返回疑点列表。"""
    text = text or ""
    suspects = []
    suspects += _check_truth_regression(text, novel_id, chapter_number)
    suspects += _check_foreshadow_schedule(text, novel_id, chapter_number)
    return suspects


def adjudicate_suspects(suspects, text, cfgs):
    """Keepers 裁决：每个疑点交对应 Agent 判定是否真矛盾。

    cfgs: {agent_type: effective_config}；缺配置的类别跳过裁决。
    """
    verdicts = []
    for s in suspects[:_ADJUDICATE_CAP]:
        agent_type = s.get("agent_type")
        cfg = cfgs.get(agent_type)
        if not cfg:
            continue
        # 正文摘录：疑点关键词附近的上下文
        excerpt = ""
        pos = text.find(s.get("excerpt", "")) if s.get("excerpt") else -1
        if pos >= 0:
            excerpt = text[max(0, pos - 120): pos + 200]
        user = (f"【设定/排期条目】\n{s.get('title', '')}\n{s.get('detail', '')}\n\n"
                f"【正文相关段落】\n{excerpt or '（未定位到原文）'}\n\n请裁决。")
        try:
            raw = call_llm_sync(
                model=cfg["model_name"],
                messages=[{"role": "system", "content": _ADJUDICATE_SYSTEM},
                          {"role": "user", "content": user}],
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=0.2, max_tokens=512,
            )
            data = extract_json_dict(raw) or {}
        except (LLMError, Exception) as e:  # noqa: B014 — 裁决失败不阻断报告
            verdicts.append({**s, "is_conflict": None, "reason": f"裁决失败：{e}"})
            continue
        verdicts.append({**s,
                         "is_conflict": bool(data.get("is_conflict")),
                         "reason": data.get("reason", ""),
                         "suggestion": data.get("suggestion", "")})
    return verdicts


def run_consistency_check(text, novel_id, chapter_number, novel=None,
                          adjudicate=False):
    """一致性链入口：确定性核对 → （可选）Keepers 裁决。"""
    text = (text or "").strip()
    if len(text) < 100:
        return {"passed": True, "suspects": [], "verdicts": [],
                "skipped": "文本过短，跳过一致性核对"}

    suspects = run_deterministic_checks(text, novel_id, chapter_number)
    verdicts = []
    if suspects and adjudicate:
        from app.config_utils import get_effective_config
        cfgs = {}
        for agent_type in {s.get("agent_type") for s in suspects[:_ADJUDICATE_CAP]}:
            if agent_type:
                cfgs[agent_type] = get_effective_config(novel, agent_type=agent_type)
        verdicts = adjudicate_suspects(suspects, text, cfgs)

    conflicts = [v for v in verdicts if v.get("is_conflict")]
    return {
        "passed": len(suspects) == 0 and not conflicts,
        "suspects": suspects,
        "verdicts": verdicts,
        "conflict_count": len(conflicts),
    }
