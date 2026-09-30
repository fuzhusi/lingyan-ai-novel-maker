"""审批流③b：角色状态回写 + 伏笔账本接线（chapter_approval 步骤③b 专用）。

设计依据（调研 2026-09-30）：
- 角色状态逐章回写是长篇质量的最强杠杆（arXiv 2503.22828 character
  sheets）；数据已在审批流 memory agent 的 character_changes 里，只差写入。
- 信任模式（用户拍板）：自动写入 + 历史链。status_json.arc_state 现值 +
  arc_history diff 链，错提取可人工纠（人物卡可编辑）。
- 伏笔账本：last_mentioned_chapter 此前是死字段（consistency_check 读它
  判推进脱班却无人写入）；本服务把它写活。
"""
import json
import logging

logger = logging.getLogger(__name__)

# 伏笔状态单步前进表（对齐 routes/knowledge/foreshadowing.py 的窄表语义）
_FORWARD = {
    "open": "buried",
    "planned": "buried",
    "buried": "advancing",
}


def _load_status_json(raw):
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def apply_arc_updates(novel_id, chapter_number, character_changes):
    """把 memory agent 的角色变化写进 Character.status_json.arc_state。

    character_changes 兼容两种形态：
    - 新 schema：{"角色名": {"want_now", "fear_now", "change_stage",
                  "relation_changes": [{"target", "relation"}]}}
    - 旧形态：{"角色名": "变化描述"}（只记 change_stage）

    只动 status_json 内的 arc_state/arc_history 键，拆书 plan 键原样保留。
    没有角色卡的（龙套）静默跳过。返回更新的角色名列表。
    """
    from app.models import Character

    if not isinstance(character_changes, dict) or not character_changes:
        return []
    updated = []
    for name, change in character_changes.items():
        name = (name or "").strip()
        if not name:
            continue
        char = Character.query.filter_by(novel_id=novel_id, name=name).first()
        if char is None:
            # 允许"陈屿"匹配"陈屿（主角）"式后缀卡名
            char = (Character.query
                    .filter(Character.novel_id == novel_id,
                            Character.name.like(f"{name}%"))
                    .first())
        if char is None:
            continue

        status = _load_status_json(char.status_json)
        arc = status.get("arc_state") or {}
        diff = {}
        if isinstance(change, dict):
            for key in ("want_now", "fear_now", "change_stage"):
                val = (change.get(key) or "").strip()
                if val and val != arc.get(key):
                    arc[key] = val
                    diff[key] = val
            for rc in (change.get("relation_changes") or []):
                if isinstance(rc, dict) and rc.get("target"):
                    relations = arc.setdefault("relations", {})
                    rel_val = (rc.get("relation") or "").strip()
                    if rel_val and relations.get(rc["target"]) != rel_val:
                        relations[rc["target"]] = rel_val
                        diff[f"关系·{rc['target']}"] = rel_val
        else:
            text = str(change).strip()
            if text and text != arc.get("change_stage"):
                arc["change_stage"] = text
                diff["change_stage"] = text

        if not diff:
            continue
        status["arc_state"] = arc
        history = status.get("arc_history") or []
        history.append({"chapter": chapter_number, "diff": diff})
        status["arc_history"] = history[-20:]   # 截最近 20 条防膨胀
        char.status_json = json.dumps(status, ensure_ascii=False)
        updated.append(name)

    if updated:
        logger.info("角色状态回写：%s（第 %s 章）", "、".join(updated), chapter_number)
    return updated


def apply_foreshadow_touches(novel_id, chapter_number, foreshadow_events,
                             known_titles=None):
    """把 memory agent 的伏笔事件写进账本：last_mentioned + 状态单步前进。

    foreshadow_events: [{"description", "foreshadow_id"}]——id 优先，
    无 id 时按 description 对活跃伏笔做标题包含匹配（prompt 里已给出
    回名录）。状态只单步前进（open/planned→buried→advancing）：
    首次提及=埋设成立；此前已被提及过（旧 last_mentioned < 本章）
    再提及=推进中。resolved/abandoned 不动。返回触碰的伏笔 id 列表。
    """
    from app.models import Foreshadowing

    if not isinstance(foreshadow_events, list) or not foreshadow_events:
        return []
    touched = []
    for ev in foreshadow_events:
        if not isinstance(ev, dict):
            continue
        fs = None
        fid = ev.get("foreshadow_id")
        if isinstance(fid, int):
            fs = Foreshadowing.query.filter_by(novel_id=novel_id, id=fid).first()
        if fs is None:
            desc = (ev.get("description") or "").strip()
            if not desc:
                continue
            candidates = (Foreshadowing.query
                          .filter_by(novel_id=novel_id)
                          .filter(Foreshadowing.status.in_(
                              ["open", "planned", "buried", "advancing",
                               "reclaimable"]))
                          .all())
            for cand in candidates:
                title = cand.title or ""
                if title and (title in desc
                              or any(seg.strip() in desc
                                     for seg in title.split("·") if seg.strip())):
                    fs = cand
                    break
        if fs is None:
            continue
        # 终态伏笔（已收/已弃）账本关门：不再记提及、不再流转
        if fs.status in ("resolved", "abandoned"):
            continue
        changed = False
        prev_mentioned = fs.last_mentioned_chapter
        if prev_mentioned != chapter_number:
            fs.last_mentioned_chapter = chapter_number
            changed = True
        # 状态单步前进：首次提及=埋设成立；此前已被提及=推进中
        mentioned_before = (prev_mentioned is not None
                            and prev_mentioned < chapter_number)
        if fs.status in _FORWARD:
            nxt = _FORWARD[fs.status]
            if nxt == "buried":
                fs.status = nxt
                changed = True
            elif nxt == "advancing" and mentioned_before:
                fs.status = nxt
                changed = True
        if changed:
            touched.append(fs.id)
    if touched:
        logger.info("伏笔账本触碰：%s（第 %s 章）", touched, chapter_number)
    return touched


def payoff_setup_note(fs, payoff_chapter_number):
    """伏笔收线时的前置展示核验（Sanderson 第一定律，advisory）。

    规则：埋设章与兑现章之间若从未有任何「提及」记录
    （last_mentioned 为空或 == 埋设章），这条线埋下后零回响——
    读者无从验证。返回提示串（无问题返回空串）。
    """
    planted = fs.planted_chapter
    if planted is None:
        return ""
    mentioned = fs.last_mentioned_chapter
    if mentioned is None or mentioned <= planted:
        return (f"伏笔「{fs.title}」第 {planted} 章埋下后从未回响，"
                f"第 {payoff_chapter_number} 章直接收线：读者可能无从验证，"
                "建议补一次前置展示或让角色点破")
    return ""
