"""叙事计划服务 —— 拆书蓝图计划值接入生成链(调研报告 §4.3/§4.5 的落地)。

三件事:
1. resolve_plan_chapters:把人物 plan 的事件锚换算成章节号(确定性查表,幂等)
2. build_plan_block:第 N 章的写作包计划块(must_payoff ≤2 + 悬挂提醒 + 禁埋令
   + 本章登场/退场角色)——jarvis-write 排程语义:「硬性任务,不是可选提醒」
3. check_retired_appearance:死人复活确定性检查(名字命中即可判,零 LLM,
   advisory 只报告不拦截)
"""
import json
import logging

from app.models import (
    db, Novel, Chapter, Character, Foreshadowing, OutlineNode,
)

logger = logging.getLogger(__name__)

def _golden_finger_block(bp_task):
    """从拆书任务的 elements_json 提取金手指规则与爽点,注入写作包。"""
    try:
        import json as _json
        elements = _json.loads(bp_task.elements_json or "{}")
        if not isinstance(elements, dict):
            return ""
    except Exception:
        return ""
    gf = elements.get("golden_finger")
    if not isinstance(gf, dict) or not gf.get("name"):
        return ""
    parts = [f"【金手指规则（{gf['name']}，每章必须遵守）】"]
    for r in gf.get("rules") or []:
        parts.append(f"- 规则：{r}")
    for sp in gf.get("satisfaction_points") or []:
        if isinstance(sp, dict):
            parts.append(f"- 爽点（{sp.get('type', '')}）：{sp.get('description', '')}")
    return "\n".join(parts[:8])  # 上限 8 行防溢出


ACTIVE_FS_STATUSES = ("planned", "buried", "advancing", "reclaimable")
_MUST_PAYOFF_LIMIT = 2       # 每章硬性回收上限(防「清账章」)
_PENDING_LIMIT = 5

# 生成期差异化红线(调研:jarvis-write 差异轴硬约束 + ASP 论文「约束少而硬」
# + "NO SUMMARY" 负向句式;约束堆叠会劣化,故只保留 3 红线 + 1 配额 + 1 置换)
DIFF_REDLINE = """【原创性红线（最高优先级，违反任何一条即废弃重写）】
R1 大纲节拍规定「必须发生什么类型的事」——必须执行，不得跳过或替换节拍功能。但节拍的具体承载（怎么发生/在哪里/用什么道具/什么天气/哪些次要人物/什么对话）必须给出你自己的新设计，不得沿用任何已有作品的原样设定。大纲与红线不矛盾：大纲说「主角被逐出师门」，你写被逐出的具体场景即可——但场景细节（执法堂?后山?当众?暗中?）必须是你自己的设计。
R2 禁止出现来源作品的专有名词（人名/门派/功法/地名/招式/道具名）；本章名词只能出自【角色设定】【场景设定】与既有正文，确需新名词时按世界观规则新造。
R3 禁止把节拍写成剧情梗概式叙述（如「随后他经历了一场考验」）——必须落成场景、动作、对话。节拍是要拍出来的戏，不是要讲明白的事。
【原创细节配额】本章正文至少 3 处大纲与设定都没规定、但完全符合设定的自创细节（一个具体物件、一个次要人物的小动作、一处环境异象、一句带信息量的闲话）——要「拔掉会心疼」的细节。
【切入角】开场避免每次都从事件正中平铺直叙：本章可尝试从中途切入、从结果写起、次要人物视角旁观、环境先行或对话先行（不强制，视节奏自然选用）。
【校准】以上要求是「别抄、别平铺」，不是「处处求奇」：允许自然过渡与普通句，差异化只落在红线与配额点上，不要为标新立异扭曲人物动机与叙事节奏。"""


def _foreshadow_capacity(novel_id):
    """活跃伏笔容量上限:max(2, 目标章数//20*3)。超容触发「禁埋令」。

    目标章数 = max(30, 已写最大章号, 大纲树规划章数)——此前只看已写章号,
    开篇(第5-19章)容量恒为 2,恰在埋伏笔高峰期触发禁埋令,与 docstring 相悖。
    """
    written_max = db.session.query(db.func.max(Chapter.chapter_number)).filter_by(
        novel_id=novel_id).scalar() or 0
    planned = db.session.query(db.func.count(OutlineNode.id)).filter_by(
        novel_id=novel_id, node_type="chapter").scalar() or 0
    target = max(30, written_max, planned)
    return max(2, target // 20 * 3)


def resolve_plan_chapters(novel_id, event_map=None):
    """把人物 plan 里的事件锚换算成章节号,写回 status_json(幂等)。"""
    if event_map is None:
        from app.services.book_deconstruct import _event_chapter_map
        event_map = _event_chapter_map(novel_id)
    for char in Character.query.filter_by(novel_id=novel_id).all():
        try:
            status = json.loads(char.status_json or "{}")
        except (json.JSONDecodeError, TypeError):
            status = {}
        plan = status.get("plan") if isinstance(status, dict) else None
        if not isinstance(plan, dict):
            continue
        changed = False
        for ev_key, ch_key in (("first_event", "first_chapter"), ("exit_event", "exit_chapter")):
            ev = (plan.get(ev_key) or "").strip()
            if ev and ev in event_map:
                plan[ch_key] = event_map[ev]
                changed = True
        if changed:
            status["plan"] = plan
            char.status_json = json.dumps(status, ensure_ascii=False)
    db.session.commit()


def build_plan_block(novel_id, chapter_number, allowed_names=None):
    """第 N 章的叙事计划块(写作包注入,层4 尾部之前的硬约束区)。

    若本书来自拆书复刻(存在以本书为目标的拆书任务),先注入**生成期差异化
    红线**(少而硬:3 红线 + 1 配额 + 1 置换,调研依据 jarvis-write/ASP 论文:
    约束要少而硬,堆软约束反而劣化)与差异轴;随后是排程任务。

    allowed_names: 本章出场角色白名单（写作页出场勾选传入）；None=不限制。
    拆书排程与本章勾选冲突时以勾选为准——排程不能命令未勾选的角色登场。

    返回 "" 表示本章无计划约束。
    """
    novel = db.session.get(Novel, novel_id)
    if not novel:
        return ""
    lines = []

    # 0) 生成期差异化红线(仅拆书复刻的本书;普通小说不注入)
    from app.models import PlagiarizeTask
    bp_task = PlagiarizeTask.query.filter_by(
        target_novel_id=novel_id, mode="deconstruct").order_by(
        PlagiarizeTask.id.desc()).first()
    if bp_task:
        lines.append(DIFF_REDLINE)
        if bp_task.axes_text and bp_task.axes_text.strip():
            lines.append(f"【本书差异轴（全篇基调，必须与上述红线共同遵守）】{bp_task.axes_text.strip()}")

    # 0.5) 金手指规则与爽点注入(写手复审:金手指是网文命根子,拆了要接上)
    if bp_task:
        gf_lines = _golden_finger_block(bp_task)
        if gf_lines:
            lines.append(gf_lines)

    # 1) must_payoff:本章应回收的伏笔(预期回收章 <= 本章,账本式而非日历式:
    #    一章脱靶不等于欠账蒸发),逾期项标注并优先;≤2 条,排序 = 最逾期优先→重要度
    due = Foreshadowing.query.filter(
        Foreshadowing.novel_id == novel_id,
        Foreshadowing.expected_resolve_chapter.isnot(None),
        Foreshadowing.expected_resolve_chapter <= chapter_number,
        Foreshadowing.status.in_(ACTIVE_FS_STATUSES),
    ).order_by(Foreshadowing.expected_resolve_chapter.asc(),
               Foreshadowing.importance.desc()).limit(_MUST_PAYOFF_LIMIT).all()
    if due:
        lines.append("【本章必须回收的伏笔（排程硬性任务，不是可选提醒）】")
        for f in due:
            overdue = chapter_number - (f.expected_resolve_chapter or 0)
            mark = f"（已逾期 {overdue} 章，本章必须收）" if overdue > 0 else ""
            lines.append(f"- {f.title or f.description[:30]}：{f.description or ''}{mark}")
        lines.append("  收伏笔要比埋伏笔好看：把揭晓放进一次冲突、一个动作、或一句没说完的话。")

    # 2) 悬挂提醒 + 禁埋令(容量 = max(2, 目标章数//20*3))
    active = Foreshadowing.query.filter(
        Foreshadowing.novel_id == novel_id,
        Foreshadowing.status.in_(ACTIVE_FS_STATUSES),
        Foreshadowing.planted_chapter.isnot(None),
        Foreshadowing.planted_chapter <= chapter_number,
    ).all()
    capacity = _foreshadow_capacity(novel_id)
    if len(active) >= capacity:
        lines.append(f"【禁埋令】当前活跃伏笔已达容量上限（{len(active)}/{capacity}），"
                     "本章不要再埋新伏笔，先把欠着的收回来。")
    pending = [f for f in active if f not in due]
    if pending:
        shown = [f for f in pending[:_PENDING_LIMIT]]
        titles = "、".join((f.title or "未命名") for f in shown)
        extra = f" 等 {len(pending)} 条" if len(pending) > _PENDING_LIMIT else ""
        lines.append(f"【仍在悬挂的伏笔（欠着账，别当成不存在）】{titles}{extra}")

    # 3) 本章登场/退场角色(人物生命周期计划)
    enter_names, exit_notes = [], []
    for c in Character.query.filter_by(novel_id=novel_id).all():
        if allowed_names is not None and c.name not in allowed_names:
            continue  # 未勾选的角色不进登场/退场排程，防"计划点名"导致角色乱入
        try:
            plan = (json.loads(c.status_json or "{}").get("plan")) or {}
        except (json.JSONDecodeError, TypeError):
            continue
        if plan.get("first_chapter") == chapter_number:
            enter_names.append(c.name)
        if plan.get("exit_chapter") == chapter_number:
            mode = plan.get("exit_mode") or "完成收线"
            exit_notes.append(f"{c.name}（{mode}）——本章完成这条线的收束")
    if enter_names:
        lines.append(f"【本章新登场的角色】{'、'.join(enter_names)}——首次出场请按人物档案建立印象")
    if exit_notes:
        lines.append(f"【本章退场的角色（人物也要回收）】{'；'.join(exit_notes)}")

    return "\n".join(lines)


def check_retired_appearance(novel_id, chapter_number, text):
    """死人复活确定性检查:计划退场章之后的正文中,名字/别名命中即疑似复活。

    advisory——返回命中名单(可能为回忆/提及/同名,由人工核实),不拦截。
    """
    hits = []
    if not text:
        return hits
    for c in Character.query.filter_by(novel_id=novel_id).all():
        try:
            plan = (json.loads(c.status_json or "{}").get("plan")) or {}
        except (json.JSONDecodeError, TypeError):
            continue
        exit_ch = plan.get("exit_chapter")
        if not exit_ch or exit_ch >= chapter_number:
            continue
        if c.name and c.name in text:
            hits.append(c.name)
    return hits
