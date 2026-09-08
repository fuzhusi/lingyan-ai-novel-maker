"""统一意见 Schema — 评审链三个意见源（Critic 分项 / 阎浮 / 白骨）的降维契约。

解决 G1：盲审返写、review 改写、Critic 分项各自为政，勾选的意见改写时
吃不全。本模块把所有意见源降维成同一结构（带稳定 id），rewrite 只吃
format_opinions_block 的产出——意见不再因来源不同而丢失。
"""
import logging

logger = logging.getLogger(__name__)


def build_merged_opinions(critic_issues=None, critic_comment="",
                          blind_reviews=None):
    """把 critic 问题清单 + 盲审文本意见合并为统一 opinion 列表。

    critic_issues: unified_review 的 issues（{dimension, severity, issue, suggestion}）
    blind_reviews: 双盲审 editors（{key, name, verdict, review}）
    id 规则：critic-N / {editor_key}-N，前端勾选回传后按 id 过滤。
    """
    opinions = []
    counters = {}
    for iss in critic_issues or []:
        if not isinstance(iss, dict):
            continue
        counters["critic"] = counters.get("critic", 0) + 1
        opinions.append({
            "id": f"critic-{counters['critic']}",
            "source": "critic",
            "severity": iss.get("severity") or "mid",
            "quote": "",
            "issue": f"[{iss.get('dimension', '')}] {iss.get('issue', '')}".strip(),
            "suggestion": iss.get("suggestion", ""),
        })
    if (critic_comment or "").strip() and not critic_issues:
        # critic 只有整体评论、无分项时，整体评论作为一条兜底意见
        opinions.append({
            "id": "critic-overall", "source": "critic", "severity": "mid",
            "quote": "", "issue": critic_comment.strip()[:500], "suggestion": "",
        })
    for ed in blind_reviews or []:
        review = (ed.get("review") or "").strip()
        if not review:
            continue
        key = ed.get("key") or "editor"
        counters[key] = counters.get(key, 0) + 1
        opinions.append({
            "id": f"{key}-{counters[key]}",
            "source": key,
            "severity": "high" if ed.get("verdict") == "弃稿" else "mid",
            "quote": "",
            "issue": review[:500],
            "suggestion": "",
        })
    return opinions


def filter_opinions(opinions, selected_ids=None):
    """按 id 集合过滤；selected_ids 为 None 时全量保留。"""
    if selected_ids is None:
        return list(opinions or [])
    ids = set(selected_ids)
    return [o for o in opinions or [] if o.get("id") in ids]


def format_opinions_block(opinions):
    """渲染为改写提示词文本块内容（空列表返回空串）。"""
    if not opinions:
        return ""
    lines = []
    for o in opinions:
        if not isinstance(o, dict):
            continue
        head = f"[{o.get('source', '?')}·{o.get('severity', 'mid')}] {o.get('issue', '')}"
        if o.get("quote"):
            head += f"（原文：{o['quote']}）"
        if o.get("suggestion"):
            head += f" → 修改方向：{o['suggestion']}"
        lines.append(f"- {head}")
    return "\n".join(lines)
