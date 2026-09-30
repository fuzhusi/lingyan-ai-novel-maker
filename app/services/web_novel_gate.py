"""网文好看度门禁（零 LLM）——与人味分双轨并行。

设计：人味分优化「不像 AI」；本模块优化「像不像能追读的网文」。
两条轨几乎正交——人味分 92+ 的章仍可能弃稿。门禁必须拆开报告。

代理指标（确定性启发式，供人工闸门参考，不替代编辑判断）：
- opening：前 200 字是否含对话/动作/反常（禁静物开场；感叹号不算动作）
- chapter_goal：**正文**是否出现目标·代价·期限强信号（大纲命中只作诊断，不计入通过）
- chapter_hook：章末 200 字是否落在外部事件，而非犹豫/睡去
- setting_dump：设定倾泻段落占比（收紧误报词）
- process_flood：电脑/文件/流程操作是否成为叙述主体
- dialogue_ratio：对白字符占比（「」“” 与西文引号）
"""
import re

_MAX_SCAN = 200_000
_OPENING_CHARS = 200
_TAIL_CHARS = 400

_DIALOGUE_MARK_RE = re.compile(r"[「“]")
# 开场动作：必须是具体动词/反常物件事件；禁止用「！」冒充动作
_ACTION_OPEN_RE = re.compile(
    r"(?:他|她|我|你|谁)[^。！？\n]{0,12}(?:推|拽|摁|拍|摔|砸|吼|喊|跑|冲|抓|踢|扔|掀|夺|挡|掐|踹|抽|拔)"
    r"|(?:门|车|灯|钟|手机|刀|杯|碗|桌|窗)[^。！？\n]{0,8}(?:开了|响了|碎了|掉了|灭了|翻了|倒了)"
    r"|^(?:滚|站住|别动|杀了|着火|出事|死了)"
)
# 目标/代价：只认强信号（弱词「之前/必须/要求」太常见）
_GOAL_SIGNAL_RE = re.compile(
    r"(?:对赌|赌约|代价|退学|开除|落选|名额|回本|凑齐|还上|保住"
    r"|非[^。！？\n]{0,6}不可|截止|期限|今晚之前|明早八点|之前要|输了就|赢了才|错过这"
    r"|落空|作废|改约|欠着|推到|悬置|放鸽子|\d+月\d+[号日]|暑假|寒假)"
)
# 章末外部事件：排除「站在/点/分/车」等日常词误报
_HOOK_EXTERNAL_RE = re.compile(
    r"(?:敲门|来电|电话响|手机(?:亮|响|震)|短信|消息(?:弹出|跳|压|连着)|屏幕(?:亮|弹)|名单|封条|搜查"
    r"|警察|尸体|血迹|钥匙|门被[^。]{0,6}(?:撞|踢|推)开|冲进|闯进|闯入"
    r"|否则|截止|明早|今晚之前|取消|退学|开除|动手|拔刀|响起"
    r"|替(?:我|你|他)[^。]{0,6}应|应下了|应了下来|约(?:战|友)|代我答应)"
)
_SOFT_END_RE = re.compile(
    r"(?:沉沉睡去|回房睡|不知过了多久|心里五味杂陈|或许|也许这就是|他沉默了|没有答案"
    r"|还是全天|犹豫|没发出去|算了|看了看表|就这样吧|生活就是这样|也许吧)"
)
# 设定倾泻：去掉「阶/分为/所谓」等易误伤的单字/泛词
_SETTING_MARK_RE = re.compile(
    r"(?:世界观设定|在这个世界上|自古以来|传说中|所谓(?:的)?(?:修行|灵力|血脉|体系)"
    r"|(?:修|武|法|灵)力境界|境界(?:划分|分为)|分为[一二三四五六七八九十\d]+(?:层|阶|级|种))"
)
# 流程操作：去掉裸「打卡/后台」（职场文误报）；要求更完整搭配
_PROCESS_MARK_RE = re.compile(
    r"(?:新建(?:文件|文件夹|文档|目录)|命名(?:为|成)|文件夹|云盘|截图|录屏|重命名"
    r"|拖入|压缩包|登录(?:系统|后台|账号)|打开(?:文档|邮箱|电脑|软件|客户端|云盘)"
    r"|复制粘贴|签名档|存档|归档|打卡(?:系统|记录|APP|截图)|后台(?:系统|账号|数据)"
    r"|系统录屏)"
)
_STAGE_CUE_RE = re.compile(r"慢半拍|静了一拍|心里一沉|脑子白了|空气中仿佛")


def _split_paras(text):
    return [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*", text) if p.strip()]


def _opening_signal(text):
    head = text[:_OPENING_CHARS]
    has_dialogue = bool(_DIALOGUE_MARK_RE.search(head))
    has_action = bool(_ACTION_OPEN_RE.search(head))
    has_process = bool(_PROCESS_MARK_RE.search(head[:120]))
    if has_dialogue or has_action:
        if has_process and not has_dialogue:
            return {"passed": False, "detail": "开场像流程说明，缺人声/冲突动作",
                    "signals": {"dialogue": has_dialogue, "action": has_action}}
        return {"passed": True, "detail": "开场含对白或动作/反常",
                "signals": {"dialogue": has_dialogue, "action": has_action}}
    return {"passed": False,
            "detail": "前 200 字未见对白/动作/反常（禁止静物·通知式开场）",
            "signals": {"dialogue": False, "action": False}}


def _goal_signal(text, outline=""):
    """目标/代价信号：**只按正文**判定是否通过，大纲命中仅作诊断。

    避免大纲里的契约「帮」正文过检——正文没写出争抢/代价就不算达标。
    """
    text_hits = _GOAL_SIGNAL_RE.findall((text or "")[:4000])
    outline_hits = _GOAL_SIGNAL_RE.findall(outline or "")
    passed = len(text_hits) >= 2
    if passed:
        detail = f"正文目标/代价强信号 {len(text_hits)} 处"
    elif outline_hits:
        detail = (f"大纲有 {len(outline_hits)} 处契约信号，但正文未体现"
                  f"（正文仅 {len(text_hits)} 处）——写进场面，不要只写在细纲里")
    else:
        detail = "正文未见目标·代价·期限强信号（本章契约可能缺失）"
    return {
        "passed": passed,
        "detail": detail,
        "count": len(text_hits),
        "text_count": len(text_hits),
        "outline_count": len(outline_hits),
    }


def _chapter_hook(text):
    tail = (text or "")[-_TAIL_CHARS:]
    if not tail.strip():
        return {"passed": False, "detail": "无章末文本"}
    soft = _SOFT_END_RE.search(tail)
    hard = _HOOK_EXTERNAL_RE.search(tail)
    if hard and not soft:
        return {"passed": True, "detail": "章末见外部事件/新信息钩"}
    if hard and soft:
        return {"passed": False, "detail": "章末钩与犹豫/睡去等软收束并存"}
    return {"passed": False,
            "detail": "章末未检出外部事件钩（禁止落在犹豫/睡去/无代价邀约）",
            "tail": tail[-40:]}


def _setting_dump(text):
    paras = _split_paras(text)
    if not paras:
        return {"passed": True, "detail": "无段落", "ratio": 0.0}
    def _is_dump(p):
        return len(p) > 80 and bool(_SETTING_MARK_RE.search(p[:80]))
    dump_paras = [p for p in paras if _is_dump(p)]
    ratio = len(dump_paras) / len(paras)
    consecutive = 0
    best = 0
    for p in paras:
        if _is_dump(p):
            consecutive += 1
            best = max(best, consecutive)
        else:
            consecutive = 0
    ok = ratio < 0.25 and best < 2
    return {
        "passed": ok,
        "detail": f"设定倾向段占比 {ratio:.0%}，最长连续 {best} 段",
        "ratio": round(ratio, 3),
        "max_consecutive": best,
    }


def _process_flood(text):
    n = max(len(re.sub(r"\s", "", text)), 1)
    hits = list(_PROCESS_MARK_RE.finditer(text))
    density = len(hits) / n * 1000
    paras = _split_paras(text)
    run = best_run = 0
    for p in paras:
        if len(p) >= 40 and _PROCESS_MARK_RE.search(p):
            run += 1
            best_run = max(best_run, run)
        else:
            run = 0
    ok = density < 2.5 and best_run < 3
    return {
        "passed": ok,
        "detail": f"流程操作密度 {density:.2f}/千字，最长连续段 {best_run}",
        "count": len(hits),
        "density_per_1k": round(density, 2),
        "max_process_paras": best_run,
    }


def _dialogue_ratio(text):
    n = max(len(text), 1)
    in_q = 0
    # 中文直角/弯引号
    for m in re.finditer(r"[「“]([^」”\n]*)[」”]", text):
        in_q += len(m.group(1))
    # 西文双引号（排除超长以免把引文段落当对白）
    for m in re.finditer(r'"([^"\n]{1,200})"', text):
        in_q += len(m.group(1))
    ratio = min(in_q / n, 1.0)
    ok = 0.06 <= ratio <= 0.55
    return {
        "passed": ok,
        "detail": f"对白占比 {ratio:.0%}（网文参考约 8%–50%）",
        "ratio": round(ratio, 3),
    }


def _stage_cues(text):
    hits = _STAGE_CUE_RE.findall(text)
    return {
        "passed": len(hits) <= 2,
        "detail": f"舞台指示腔 {len(hits)} 处（慢半拍/心里一沉等）",
        "count": len(hits),
    }


# 情绪唤醒词单一来源在 tension_bus（峰值检测与强度审计共用，防两处漂移）
from app.services.tension_bus import (
    AROUSAL_RE as _PEAK_AROUSAL_RE,
    parse_outline_field as _parse_outline_field,
)

# 断章四法（网文工业 + Swain Scene-Sequel 交叉印证）：章末必须断在变化时刻。
# 四类信号的词表口径刻意宽松（mid 软检查起步，实测定标后再定档）。
_ENDING_DECISION_RE = re.compile(
    r"决定|答应|拒绝|摊牌|认了|回绝|应下|允了|选了|定了|动身|出发|启程|辞职|退了|告吹|应了"
    r"|就(?:去|回|来|走|办|到)|明天就|这就定")
_ENDING_DISCOVERY_RE = re.compile(
    "发现|原来|真相|才晓得|才知道|揭晓|认出|看穿|败露|曝光|浮出|到账|名单|出来了")
_ENDING_MISJUDGE_RE = re.compile(r"误会|错认|冤枉|错怪|看走眼|以为[^。]{0,10}其实|认错[^人]{0,2}了")
_ENDING_COST_RE = re.compile(
    r"失去|去世|走了|没了|迟到|错过|泡汤|作废|赔了|罚了|丢了|分手|决裂|翻脸|砸了|黄了|鸽了")


def _chapter_ending(text, quiet_register=False):
    """断章四法：章末 300 字须落在「决定/发现/误判/代价」之一的变化时刻。

    依据（调研交叉印证）：追读率八成取决于章末最后几行；Swain 的
    scene-sequel 循环要求章末是 disaster 或 decision。安静向基调
    （【情感基调】标注安静/克制/白描）只提示不扣分——氛围收尾是合法写法。
    """
    tail = (text or "")[-300:]
    if not tail.strip():
        return {"passed": True, "detail": "无章末文本"}
    hits = []
    if _ENDING_DECISION_RE.search(tail):
        hits.append("决定")
    if _ENDING_DISCOVERY_RE.search(tail):
        hits.append("发现")
    if _ENDING_MISJUDGE_RE.search(tail):
        hits.append("误判")
    if _ENDING_COST_RE.search(tail):
        hits.append("代价")
    if hits:
        return {"passed": True,
                "detail": f"章末落在变化时刻：{'/'.join(hits)}"}
    soft = _SOFT_END_RE.search(tail)
    if quiet_register:
        return {"passed": True,
                "detail": "安静基调的氛围收尾（未检出四法信号，不扣分）"}
    detail = "章末未落在变化时刻（决定/发现/误判/代价）"
    if soft:
        detail += "，且呈总结式收尾——断在变化发生那一刻，别断在回味里"
    return {"passed": False, "detail": detail, "hits": 0}


def _emotion_peak(text):
    """章内情绪峰值缺失（软检查，mid 风险，不阻断）。

    实测定标（书 1《你应该好好爱自己》24 章）：11/24 章叹号为零、
    全书无强度曲线——"平淡"最鲁棒的信号就是幅宽塌平，不是任何词表。
    口径：叹号 0 且 问号 < 2/千字 且 唤醒词 < 2/千字 → 峰值缺失。
    阈值刻意宽松（多数克制文风不该被误伤），命中即提示"挑一拍正面写足"。
    """
    n = max(len(text), 1)
    per_k = 1000.0 / n
    excl = text.count("！") + text.count("!")
    ques = (text.count("？") + text.count("?")) * per_k
    arousal = len(_PEAK_AROUSAL_RE.findall(text)) * per_k
    flat = excl == 0 and ques < 2.0 and arousal < 2.0
    return {
        "passed": not flat,
        "detail": (f"叹号 {excl}、问号 {ques:.1f}/千字、唤醒词 {arousal:.1f}/千字"
                   + ("——全章情绪幅宽塌平，至少一拍把冲突正面写足" if flat else "")),
        "excl": excl,
        "question_per_k": round(ques, 1),
        "arousal_per_k": round(arousal, 1),
    }


# 信息密度：前 300 字「人物+异常」可懂（编辑只看前三章，首屏定生死）
_ANOMALY_RE = re.compile(
    r"突然|竟然|居然|不对劲|出事|意外|陌生|头一回|第一次|反常|异样|怪|从没|罕见|偏偏|偏偏就|就在这时")


def _info_density(text, protagonist_names=None, event_count=None,
                  is_first_chapter=False):
    """信息密度：①首章前 300 字「人物+异常」可懂；②每章有用变化事件数。

    事件数来自 chapter_events 提取（审批前已产出，纯读数）；event_count
    为 None 时（调用方拿不到事件）跳过②，只查首章①。
    """
    problems = []
    if is_first_chapter:
        head = (text or "")[:300]
        has_person = bool(protagonist_names) and any(
            n and n in head for n in protagonist_names)
        has_anomaly = bool(_ANOMALY_RE.search(head))
        if not has_person:
            problems.append("前300字未见具名人物（读者不知道跟谁入局）")
        if not has_anomaly:
            problems.append("前300字未见异常信号（平静开场缺「有事」预告）")
    if event_count is not None and event_count < 2:
        problems.append(f"本章有效事件仅 {event_count} 个（<2）：章内缺有用变化")
    if not problems:
        return {"passed": True, "detail": "信息密度达标"}
    return {"passed": False, "detail": "；".join(problems)}


def analyze_web_novel(text, outline="", event_count=None,
                      is_first_chapter=False, protagonist_names=None):
    """好看度双轨报告（零 LLM）。

    event_count/is_first_chapter/protagonist_names: 信息密度检查的可选
    输入（chapter_runner 传，其他调用方可省略——缺省时对应子检查跳过）。

    Returns:
        {
          "passed": bool,          # 无 high 风险项
          "readability_score": 0-100,
          "checks": [{name, passed, risk, detail, ...}],
          "hint": str,
        }
    """
    text = (text or "")[:_MAX_SCAN]
    if len(text.strip()) < 200:
        return {"passed": True, "readability_score": None, "checks": [],
                "skipped": "文本过短，跳过好看度检测"}

    from app.services.tension_bus import quiet_register_of
    tone_text = _parse_outline_field(outline, "情感基调") if outline else ""

    checks_raw = [
        ("opening", "开场钩（前200字）", _opening_signal(text), 25),
        ("chapter_goal", "本章目标/代价信号", _goal_signal(text, outline), 20),
        ("chapter_hook", "章尾外部事件钩", _chapter_hook(text), 25),
        ("setting_dump", "设定倾泻", _setting_dump(text), 10),
        ("process_flood", "流程操作灌水", _process_flood(text), 12),
        ("dialogue_ratio", "对白占比", _dialogue_ratio(text), 5),
        ("stage_cues", "舞台指示腔", _stage_cues(text), 3),
        ("emotion_peak", "章内情绪峰值", _emotion_peak(text), 8),
        ("chapter_ending", "断章四法", _chapter_ending(
            text, quiet_register=quiet_register_of(tone_text)), 8),
        ("info_density", "信息密度", _info_density(
            text, protagonist_names=protagonist_names,
            event_count=event_count, is_first_chapter=is_first_chapter), 10),
    ]
    checks = []
    deduction = 0
    for key, name, res, weight in checks_raw:
        passed = bool(res.get("passed"))
        risk = "low" if passed else ("high" if weight >= 20 else "mid")
        item = {"key": key, "name": name, "passed": passed, "risk": risk}
        item.update({k: v for k, v in res.items() if k != "passed"})
        checks.append(item)
        if not passed:
            deduction += weight if risk == "high" else max(weight // 2, 1)

    score = max(0, min(100, 100 - deduction))
    highs = [c for c in checks if c["risk"] == "high"]
    hint = ""
    if highs:
        hint = "好看度不达标：优先改大纲/补本章契约与章尾钩，而不是再跑去AI收敛。"
    return {
        "passed": not highs,
        "readability_score": score,
        "checks": checks,
        "hint": hint,
    }


def build_readability_instructions(text, outline=""):
    """把好看度问题转成可注入生成链的修正指令（正向，不是禁词）。"""
    rep = analyze_web_novel(text, outline=outline)
    if rep.get("readability_score") is None:
        return ""
    lines = []
    for c in rep.get("checks", []):
        if c.get("passed"):
            continue
        key = c.get("key")
        if key == "opening":
            lines.append("开场改为第一行人声/动作/反常，前三行立起问题或压力，禁止静物与通知腔")
        elif key == "chapter_goal":
            lines.append("正文须体现本章契约：他要什么 + 谁拦他 + 不做成会失去什么（写进场面，不要说明）")
        elif key == "chapter_hook":
            lines.append("章尾落在外部事件/倒计时/既成事实，并写清代价；禁止犹豫收束或回房睡去")
        elif key == "setting_dump":
            lines.append("拆掉成段设定说明：一章至多一条设定且必须挂在动作或道具上")
        elif key == "process_flood":
            lines.append("删减文件/登录/截图类流程描写，戏在人物选择与冲突，不在操作步骤")
        elif key == "dialogue_ratio":
            lines.append("增加有算盘与信息差的对白，或压纯独白；避免自说自话")
        elif key == "stage_cues":
            lines.append("删「慢半拍/心里一沉」类舞台指示，改成可拍摄的身体动作")
        elif key == "emotion_peak":
            lines.append("全章幅宽塌平：挑冲突最重的一拍正面写足——允许失控、"
                         "吼/摔/眼泪直接上，别再用动作暗示带过情绪")
        elif key == "chapter_ending":
            lines.append("断章落在变化时刻：决定/发现/误判/代价任选其一，"
                         "切在事情发生的那一拍，禁止总结式回味收尾")
        elif key == "info_density":
            lines.append("信息密度不足：首屏立起人物与异常，本章至少推进两个"
                         "有用变化（事件要有结果，不是只起头）")
    if not lines:
        return ""
    return ("【追读结构修正 — 优先于文风微调】\n" + "\n".join(f"- {ln}" for ln in lines))
