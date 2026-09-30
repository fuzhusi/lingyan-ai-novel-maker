"""细纲戏剧字段校验（零 LLM）。

策略（兼顾「无戏不写」与「旧大纲可用」）：
- 严格阻断：过短 / 既无字段也无叙事语义（无法施工）
- 软通过：旧格式实质大纲（有叙事/节拍/部分字段）→ 允许进正文，
  但生成时注入缺失的戏剧备注（契约/章尾钩硬要求），warnings 保留给前端
"""
import re

_MIN_OUTLINE_CHARS = 50
# 旧格式实质大纲：更长 + 含叙事动词即可软通过
_LEGACY_MIN_CHARS = 100

_EVENT_MARK = re.compile(r"【核心事件】|【本章事件】")
_HOOK_MARK = re.compile(r"【结尾钩子】|【章尾钩子】")
_CONTRACT_MARK = re.compile(
    r"【本章契约】|【契约】|他要什么|谁拦|不做成会失去|本章目标"
)
_BEAT_MARK = re.compile(r"【场景节拍】")
# 兜底钩子语义：须是事件/代价，不能出现裸「退/明天」
_HOOK_FALLBACK = re.compile(
    r"(?:钩子|悬念|留下[^。]{0,10}(?:悬念|疑问)|否则|代价|退学|退出|退场"
    r"|失踪|被发现|动手|明早|今晚之前|最后通牒|期限|被赶|被杀|对决)"
)
# 叙事语义：旧大纲即使无【】字段，能读出「有人在做事」即可施工
_LEGACY_NARRATIVE = re.compile(
    r"(?:主角|他|她|男主|女主|我)[^。！？\n]{2,30}"
    r"(?:决定|被迫|发现|遇到|得到|失去|被赶|被杀|对赌|前往|闯入|拒绝|答应|偷|抢|逃)"
    r"|(?:冲突|危机|转折|高潮|铺垫|对决|摊牌|背叛|觉醒)"
)


def validate_outline_drama(outline):
    """校验大纲是否具备可施工的戏剧结构。

    Returns:
        {
          "ok": bool,              # 可否进入正文（含软通过）
          "soft_pass": bool,       # 旧格式软通过（建议补字段，不阻断）
          "blocking": [str],
          "warnings": [str],
          "has": {event, hook, contract, beats},
        }
    """
    text = (outline or "").strip()
    has = {
        "event": bool(_EVENT_MARK.search(text)),
        "hook": bool(_HOOK_MARK.search(text)),
        "contract": bool(_CONTRACT_MARK.search(text)),
        "beats": bool(_BEAT_MARK.search(text)),
    }
    if not has["event"] and re.search(
            r"(?:谁|他|她|主角|男主|女主)[^。]{0,20}"
            r"(?:发现|决定|被迫|得到|失去|遇到|对赌|被赶|被杀)", text):
        has["event"] = True
    if not has["hook"] and _HOOK_FALLBACK.search(text):
        has["hook"] = True
    has_narrative = has["event"] or has["beats"] or bool(_LEGACY_NARRATIVE.search(text))

    blocking = []
    warnings = []

    if len(text) < _MIN_OUTLINE_CHARS:
        blocking.append(f"细纲过短（{len(text)} 字 < {_MIN_OUTLINE_CHARS}）")
    elif not has_narrative and len(text) < _LEGACY_MIN_CHARS:
        blocking.append("大纲过短且无法识别事件/节拍，无法施工")
    elif not has_narrative:
        blocking.append("大纲缺少可识别的核心事件/场景节拍/叙事推进，无法施工")

    if not has["hook"]:
        if has_narrative and len(text) >= _LEGACY_MIN_CHARS:
            warnings.append("大纲缺少【结尾钩子】——生成时将注入章尾事件钩硬要求")
        else:
            blocking.append("大纲缺少【结尾钩子】——章尾必须留下外部事件悬念")

    if not has["contract"]:
        warnings.append("大纲缺少【本章契约】（他要什么/谁拦他/代价）——生成时将注入戏剧施工提醒")
    if has["beats"] and not has["event"]:
        warnings.append("有场景节拍但无章级核心事件，注意拍与拍要合成一条因果线")

    soft_pass = (not blocking) and (
        (not has["hook"]) or (not has["contract"]) or
        (not (has["event"] or has["beats"]) and has_narrative)
    )
    return {
        "ok": not blocking,
        "soft_pass": soft_pass,
        "blocking": blocking,
        "warnings": warnings,
        "has": has,
    }


def outline_gate_error(outline):
    """阻断时返回用户可读错误串；可通过（含软通过）则返回空串。"""
    report = validate_outline_drama(outline)
    if report["ok"]:
        return ""
    return "细纲未通过戏剧门禁：" + "；".join(report["blocking"]) + \
        "。请先补全大纲（核心事件 + 结尾钩子，最好含本章契约）。"


def write_ready_outline(outline):
    """正文生成前的门禁决策。

    Returns:
        {
          "ok": bool,
          "soft_pass": bool,
          "blocking": [...],
          "warnings": [...],
          "has": {...},
          "effective_outline": str,   # 软通过时附加戏剧备注，供 writer 注入
          "drama_notes": str,         # 缺失字段的正向施工备注
        }
    """
    report = validate_outline_drama(outline)
    notes = []
    has = report["has"]
    if report["ok"] and not has.get("contract"):
        notes.append(
            "【本章契约·系统补注】正文必须体现：他要什么（可量化）／谁拦他／"
            "不做成会失去什么。写进场面，禁止说明文。")
    if report["ok"] and not has.get("hook"):
        notes.append(
            "【结尾钩子·系统补注】章尾必须落在外部事件/倒计时/既成事实，"
            "并写清代价；禁止犹豫收束、回房睡去、无代价邀约。")
    drama_notes = "\n".join(notes)
    effective = (outline or "").strip()
    if drama_notes:
        effective = (effective + "\n\n" + drama_notes) if effective else drama_notes
    return {
        **report,
        "effective_outline": effective,
        "drama_notes": drama_notes,
    }
