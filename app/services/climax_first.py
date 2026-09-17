"""高潮先行大纲模式（BiT-MCTS 思路的轻量落地）。

不跑真 MCTS：两次 LLM 调用——
1. 先定高潮：从构思/主题/角色提炼本篇核心冲突与高潮节点
2. 倒推铺垫 + 顺推收束：补齐高潮前后的节点

用于短篇 expand 与长篇卷纲的可选模式。
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

_CLIMAX_SYSTEM = (
    "你是小说结构策划。先锁定高潮，再铺垫与收束。\n"
    "输出严格 JSON：\n"
    '{"climax":{"title":"...","core_conflict":"...","emotional_peak":"..."},'
    '"before":[{"title":"...","summary":"..."}],'
    '"after":[{"title":"...","summary":"..."}]}\n'
    "before 为高潮前铺垫节点（按时间顺序），after 为高潮后收束节点。"
    "只输出 JSON，不要解释。"
)


def plan_climax_first(concept, cfg, n_before=3, n_after=2):
    """高潮先行：先定高潮，再双向补全节点。

    Returns:
        {"climax": {...}, "nodes": [{"position":"before|climax|after",
         "title","summary"}, ...]} 或 {"error": str}
    """
    concept = (concept or "").strip()
    if len(concept) < 20:
        return {"error": "构思过短，无法高潮先行规划"}
    if not cfg:
        return {"error": "缺少 outline Agent 配置"}
    from app.services.llm import call_llm_sync, LLMError
    user = (
        f"【构思/主题】\n{concept}\n\n"
        f"要求：高潮前 {n_before} 个铺垫节点，高潮后 {n_after} 个收束节点。"
        f"高潮必须是核心冲突的爆发点，不是平铺事件。")
    try:
        raw = call_llm_sync(
            model=cfg["model_name"],
            messages=[
                {"role": "system", "content": _CLIMAX_SYSTEM},
                {"role": "user", "content": user},
            ],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.7, max_tokens=2000)
    except LLMError as e:
        return {"error": str(e)}
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("高潮先行 JSON 解析失败: %s", raw[:150])
        return {"error": "规划输出不是合法 JSON"}

    climax = data.get("climax") if isinstance(data, dict) else None
    if not isinstance(climax, dict) or not climax.get("title"):
        return {"error": "未产出高潮节点"}

    nodes = []
    for n in (data.get("before") or [])[:n_before]:
        if isinstance(n, dict) and n.get("title"):
            nodes.append({"position": "before", "title": n["title"],
                          "summary": n.get("summary", "")})
    nodes.append({"position": "climax", "title": climax["title"],
                  "summary": climax.get("core_conflict")
                  or climax.get("emotional_peak", "")})
    for n in (data.get("after") or [])[:n_after]:
        if isinstance(n, dict) and n.get("title"):
            nodes.append({"position": "after", "title": n["title"],
                          "summary": n.get("summary", "")})
    return {"climax": climax, "nodes": nodes}
