"""张力总线（tension bus）——全书强度曲线的确定性推导（零 LLM）。

机制来源（开源调研 2026-09-28）：
- jarvis-write（藏山）tension_bus：全书 1-5 曲线贯穿，卷内波形 + 卷间抬升，
  由蓝图章节定位确定性推导，「跨章不许是平线」；
- jarvis-write 张力档→力度档映射：每场一个明确数字（1 压住写 → 5 全力爆发），
  替代笼统的"要有起伏"；
- NovelForge 卡片级生成配置：高张力场景单独调 temperature（机制化的放开写）。

设计约束（灵砚纪律）：
- 确定性优先：不问 LLM，全部由大纲字段/伏笔排程推导；
- 不加提示词：张力只以「一档数字 + 一行力度说明」进入 prompt；
- 软目标：检测只做审计与定向修正建议，不做词表禁令（配额悖论教训）。
"""
import logging
import re

logger = logging.getLogger(__name__)

# 张力档 → 力度说明（jarvis-write 力度档映射的本地化）。一行进 prompt，
# 不展开成多句指令——力度必须可在执行层被"看见"（temperature 映射）。
_TENSION_DIRECTIVES = {
    1: "压着写：情绪收在动作底下，压力留给读者自己感到",
    2: "平稳推进：日常质感，冲突只露苗头",
    3: "矛盾上桌：分歧摆到明面，来回要见力度",
    4: "强冲突：正面交锋，情绪允许失控，动作幅度放大",
    5: "全力爆发：全书级场面，撕开写，不留余地",
}

# 高张力关键词（【本章定位】/节拍文本命中即抬档）
_HIGH_WORDS = ("高潮", "爆发", "决战", "摊牌", "翻脸", "决裂", "撕破", "失控",
               "对峙", "崩塌", "摊上事", "摊牌了", "生死")
_MID_WORDS = ("转折", "冲突", "争执", "吵架", "揭穿", "点破", "摊开", "反弹",
              "交锋", "撞上", "出事")
_LOW_WORDS = ("铺垫", "日常", "过渡", "收束", "缓冲", "闲笔", "稳定", "温情")

# 节拍内冲突词：用于给单拍定位峰值位置（冲突拍吃最高档）
_BEAT_PEAK_WORDS = ("冲突", "对峙", "摊牌", "吵架", "爆发", "揭穿", "点破", "打",
                    "骂", "冲上去", "翻脸", "砸", "吼", "喊")


def parse_scene_beats(outline):
    """解析大纲【场景节拍】为有序节拍列表（旧格式/缺失返回 []）。

    兼容两种排法：分号连排（"1.xxx；2.xxx"）与换行排（每行一拍）。
    长度 <10 的碎屑丢弃；少于 2 拍视为"没有可拆的节拍"。
    """
    m = re.search(r"【场景节拍】(.+?)(?=\n【|$)", outline or "", re.S)
    if not m:
        return []
    raw = m.group(1).strip()
    parts = re.split(r"[；;\n]", raw)
    beats = []
    for p in parts:
        p = re.sub(r"^\s*\d+\s*[.、)）]\s*", "", p.strip())
        if len(p) >= 10:
            beats.append(p)
    return beats


def parse_outline_field(outline, field):
    """取大纲 7 字段之一的文本（找不到返回空串）。"""
    m = re.search(rf"【{field}】(.+?)(?=\n【|$)", outline or "", re.S)
    return m.group(1).strip() if m else ""


def chapter_tension(novel_id, chapter_number, outline=""):
    """推导本章张力档（1-5）。

    依据（全部确定性）：
    1. 【本章定位】关键词：高潮系 +2 / 转折系 +1 / 铺垫系 -1；
    2. 伏笔到期压力：本章到期（expected==n）+1，逾期未收 +1（封顶 +2）；
    3. 基线 2，夹在 [1, 5]。
    """
    level = 2
    positioning = parse_outline_field(outline, "本章定位")
    text = positioning or ""
    if any(w in text for w in _HIGH_WORDS):
        level += 2
    elif any(w in text for w in _MID_WORDS):
        level += 1
    if any(w in text for w in _LOW_WORDS):
        level -= 1

    try:
        from app.models import Foreshadowing
        pending = (Foreshadowing.query.filter_by(novel_id=novel_id)
                   .filter(Foreshadowing.status.in_(
                       ["open", "planned", "buried", "advancing", "reclaimable"]))
                   .all())
        pressure = 0
        for f in pending:
            expected = f.expected_resolve_chapter or f.resolve_chapter
            if expected is None:
                continue
            if expected == chapter_number:
                pressure += 1
            elif expected < chapter_number:
                pressure += 1
            if pressure >= 2:
                break
        level += pressure
    except Exception as exc:
        logger.warning("tension_bus 伏笔压力推导降级: %s", exc)

    # 卷末抬升（jarvis-write 卷间抬升的轻量版）：本章是大纲树某卷的最后一章
    # （下一章已挂到别的卷节点）→ +1。无大纲树/未挂节点时静默跳过。
    try:
        from app.models import Chapter, OutlineNode
        ch = Chapter.query.filter_by(novel_id=novel_id,
                                     chapter_number=chapter_number).first()
        cur_parent = None
        if ch and ch.outline_node_id:
            node = OutlineNode.query.get(ch.outline_node_id)
            cur_parent = node.parent_id if node else None
        if cur_parent:
            nxt = Chapter.query.filter_by(novel_id=novel_id,
                                          chapter_number=chapter_number + 1).first()
            if nxt and nxt.outline_node_id:
                nnode = OutlineNode.query.get(nxt.outline_node_id)
                nxt_parent = nnode.parent_id if nnode else None
                if nxt_parent is not None and nxt_parent != cur_parent:
                    level += 1
    except Exception as exc:
        logger.warning("tension_bus 卷末抬升推导降级: %s", exc)

    return max(1, min(5, level))


def beat_tensions(chapter_level, beats):
    """把章张力档摊成逐拍曲线：峰值拍吃满章档，末拍留余韵。

    形状规则（对齐 jarvis-write adjust_scene_waves，开源审查 2026-09-28 复核）：
    - 峰值默认放**倒数第二拍**——高潮摆最后是"为了炸而炸"，爆点后要给一拍收余韵；
    - 冲突词命中的拍优先钦点为峰值（作者/大纲的显性安排最高）；
    - 峰值前从 level-2 线性爬升到 level-1（渐升，不是平台）；
    - 峰值后压到 level-2（余韵）。
    跨拍曲线必须不平——这正是 jarvis-write「跨章不许是平线」在章内的版本。
    """
    n = len(beats)
    if n == 0:
        return []
    peak = None
    for i, b in enumerate(beats):
        if any(w in b for w in _BEAT_PEAK_WORDS):
            peak = i
            break
    if peak is None:
        peak = max(0, n - 2)

    floor = max(1, chapter_level - 2)
    sub = max(1, chapter_level - 1)
    levels = []
    for i in range(n):
        if i == peak:
            lv = chapter_level
        elif i > peak:
            lv = max(1, chapter_level - 2)      # 余韵段
        elif peak == 0:
            lv = sub
        else:
            lv = sub if i >= peak / 2 else floor   # 爬升段：过半升一档
        levels.append(max(1, min(5, lv)))
    return levels


def tension_directive(level):
    """张力档对应的一行力度说明（进 prompt 的唯一文本）。"""
    return _TENSION_DIRECTIVES.get(max(1, min(5, int(level))), _TENSION_DIRECTIVES[3])


def temperature_for_level(base_temp, level):
    """张力档 → 采样温度映射（NovelForge 卡片级配置机制）。

    高张力放开采样（罕见/生猛词更容易被选到），低张力收紧。
    幅度刻意小（≤±0.1），不改变模型整体行为面；同一章内峰值拍
    温度必须高于铺垫拍——这是"力度档"可被执行层看见的方式。
    """
    base = float(base_temp or 0.8)
    level = max(1, min(5, int(level)))
    if level >= 4:
        return min(1.0, round(base + 0.1, 2))
    if level == 3:
        return min(1.0, round(base + 0.05, 2))
    if level <= 1:
        return max(0.6, round(base - 0.05, 2))
    return base


# 情绪唤醒词表（峰值检测与强度审计共用；单一来源，防两处漂移）
AROUSAL_RE = re.compile(r"吼|喊|怒|骂|砸|摔|拍桌|炸|冲上|嘶吼|发抖|颤抖|眼泪|哭")


def measured_intensity(text):
    """正文情绪强度的只读审计值（不改稿，仅供对比张力档）。

    口径（配额悖论教训：统计软目标，不做词禁）：
    - 叹号/问号是情绪幅宽最鲁棒的代理（实测书 1 有 11/24 章叹号为零）；
    - 唤醒词命中做次要项。返回每千字密度，供 runner 记录与 Reflexion。
    """
    text = text or ""
    if len(text) < 200:
        return None
    per_k = 1000.0 / len(text)
    marks = (text.count("！") + text.count("!")) * 2 + text.count("？") + text.count("?")
    arousal = len(AROUSAL_RE.findall(text))
    return round((marks + arousal) * per_k, 1)


def intensity_gap_note(chapter_level, measured, tone_text=""):
    """章张力档与实测强度的落差提示（落差大 → 进 Reflexion 供下章修正）。

    返回空串表示无落差。阈值按实测数据定标：书 1 均值档位下的
    平淡章 measured ≈ 5-15；张力档 ≥4 的章实测应显著高于此。
    基调感知：大纲【情感基调】标注安静/克制/隐忍/白描的书，
    期望下限减半——安静的煎熬是合法写法，审计不该把"稳"当"平"。
    """
    if measured is None:
        return ""
    quiet_register = bool(re.search(r"安静|克制|隐忍|白描|冷峻|平实", tone_text or ""))
    floor = {1: 0, 2: 3, 3: 8, 4: 15, 5: 25}.get(chapter_level, 8)
    if quiet_register:
        floor = max(0, floor // 2)
    if chapter_level >= 3 and measured < floor:
        return (f"本章张力档 {chapter_level} 但正文情绪强度仅 {measured}/千字"
                f"（档位参考下限 {floor}）：场面写得平，"
                "下一章把冲突拍正面摊开写，允许情绪失控与大幅度动作。")
    return ""
