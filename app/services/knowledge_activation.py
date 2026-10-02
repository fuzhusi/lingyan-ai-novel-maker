"""知识激活服务（调研 v2 第 1 步）：policy 最小集的解析、命中与近文采集。

policy 最小集（决策记录 docs/知识库与上下文注入调研-2026-09.md v2）：
    {"mode": "auto|always|keywords|off", "keys": ["触发词", ...]}
- auto    默认值，精确复刻现状（名册过滤 + 语义可用则剪枝 + 全量兜底）
- always  常驻：免疫剪枝，只要条目存在就注入（仍受预算约束）
- keywords 标题或 keys 命中「近两章正文」才注入
- off     不注入

兼容红线：默认全 auto 时行为与升级前逐字节一致（验收含对比）。
"""
import json
import logging

logger = logging.getLogger(__name__)

_VALID_MODES = ("auto", "always", "keywords", "off")


def parse_policy(raw):
    """解析 injection_policy JSON，容错并归一化到合法 mode。"""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    mode = data.get("mode") if data.get("mode") in _VALID_MODES else "auto"
    keys = data.get("keys") or []
    if not isinstance(keys, list):
        keys = []
    return {"mode": mode, "keys": [str(k) for k in keys if str(k).strip()]}


def keywords_hit(policy, title, recent_text):
    """keywords 模式命中判定：标题或任一触发词出现在近两章正文中。"""
    if not recent_text:
        return False
    needles = [ (title or "").strip() ]
    needles += [k.strip() for k in (policy.get("keys") or []) if k.strip()]
    needles = [n for n in needles if len(n) >= 2]   # 过滤单字噪声
    return any(n in recent_text for n in needles)


def gather_recent_text(novel_id, before_chapter, tail=4000):
    """近两章正文尾部（keywords 命中的扫描窗口，等价 ST scan_depth=2）。"""
    from app.models import Chapter
    chapters = (Chapter.query
                .filter_by(novel_id=novel_id)
                .filter(Chapter.chapter_number < before_chapter)
                .order_by(Chapter.chapter_number.desc())
                .limit(2).all())
    parts = []
    for ch in chapters:
        if ch.versions:
            text = ch.versions[-1].content or ""
            parts.append(text[-tail:])
    return "\n".join(parts)


def split_modes(entries, policy_of):
    """按 policy 把条目分成 auto/always/keywords/off 四桶。

    entries: 条目对象或 dict（含 id）；policy_of: callable(entry)->policy dict。
    返回 {"auto": [...], "always": [...], "keywords": [...], "off": [...]}。
    """
    buckets = {"auto": [], "always": [], "keywords": [], "off": []}
    for e in entries:
        mode = policy_of(e).get("mode", "auto")
        buckets.get(mode, buckets["auto"]).append(e)
    return buckets


def dedupe_by_id(items):
    """按 id 去重保序（always/keywords/auto 合并时防重复注入）。"""
    seen = set()
    out = []
    for it in items:
        key = it.get("id") if isinstance(it, dict) else id(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def default_policy_for(title):
    """拆书落库条目的默认策略：keywords + 标题触发（防全 auto 退化成全量注入）。"""
    return json.dumps({"mode": "keywords", "keys": [(title or "").strip()]},
                      ensure_ascii=False)
