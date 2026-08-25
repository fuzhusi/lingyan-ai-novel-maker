"""Skill Gate — 技能执行质量门禁（写后确定性校验）。

设计原则（借鉴 InkOS 的 Audit→Revise 循环与 Lorn.NovelWriteSkills 的质量门禁）：
- Skill 管「怎么写」（提示词注入），Gate 管「写没做到」（生成后验收）
- 只做确定性检测（正则/统计），不调 LLM——零成本、零误报可控
- 只校验当前激活的技能对应的检查项
- 违规输出带原文摘录，供句子级定向修订（而非整章重写）

已知边界：中文正则启发式存在漏检/极少数误检，定位是"抽检提示"而非法律判决。
"""
import re

# ---------------------------------------------------------------------------
# 检测器实现
# ---------------------------------------------------------------------------

# 对话修饰语黑名单（dialogue_realism / dialogue_humanize）
# 覆盖三类：① X声道式 ② 笑/哭相动词+道 ③ 情绪副词+地道
_DIALOGUE_MODIFIER_RE = re.compile(
    r"(?:沉声|厉声|柔声|低声|高声|朗声|冷冷|幽幽|淡淡)(?:道|地说)"
    r"|(?:冷笑|轻笑|苦笑|干笑|讪笑|狞笑|媚笑|惨然|凄然|哽咽)道"
    r"|(?:愤怒|激动|平静|缓缓|轻轻|慢慢|严肃|温柔|无奈|认真)地(?:说道?|问道?|喊道?)"
    r"|没好气地道|咬着牙道"
)

# 三连排比（rhythm_breaking）：同一句内三处「有的…」「一是…」等
_PARALLEL_TRIAD_RE = re.compile(
    r"(?:有的|一个|一种|仿佛|像是)[^。！？；\n]{1,16}(?:有的|一个|一种|仿佛|像是)"
    r"[^。！？；\n]{1,16}(?:有的|一种|像是)"
)

# 模板结构标记（deai_structure）
_TEMPLATE_STRUCTURE_RE = re.compile(r"(首先|其次|再者|紧接着|最后)[，,、]")

# 段末升华（imperfection）：结尾区域的顿悟/哲理句
_ENDING_UPLIFT_RE = re.compile(
    r"[^。\n]{0,24}(?:终于明白|终于读懂|明白了.{0,8}良苦用心"
    r"|命运的齿轮|这或许就是|也许，?这就是|这就是(?:成长|人生|生活))[^。\n]{0,24}。?"
)

# 直述情绪标签（show_dont_tell）
_TELL_EMOTION_RE = re.compile(
    r"(?:他|她|它|[一-龥]{1,3})(?:的?心(?:中|里))?(?:感到|觉得|不禁)?"
    r"(?:很|十分|非常|无比|格外)(?:紧张|伤心|愤怒|害怕|难过|开心|激动|失望|委屈)"
)

# 抽象感官词（sensory_concrete / sensory_detail）
_ABSTRACT_SENSORY_RE = re.compile(
    r"(?:一股|阵)(?:难闻|刺鼻|奇怪|说不清)[的]?(?:气味|味道)"
    r"|(?:周围|屋里|房间里)(?:十分|非常|格外)?安静"
)


def _excerpts(text, pattern, limit=5, radius=18):
    """返回 pattern 在 text 中的违规摘录列表（带少量上下文）。"""
    out = []
    for m in pattern.finditer(text):
        s = max(0, m.start() - radius)
        e = min(len(text), m.end() + radius)
        frag = text[s:e].replace("\n", " ")
        mark = ("…" if s > 0 else "") + frag + ("…" if e < len(text) else "")
        out.append(mark)
        if len(out) >= limit:
            break
    return out


def _count_dialogue_modifiers(text):
    hits = []
    for m in _DIALOGUE_MODIFIER_RE.finditer(text):
        s = max(0, m.start() - 14)
        e = min(len(text), m.end() + 14)
        hits.append(("…" if s > 0 else "") + text[s:e].replace("\n", " ")
                    + ("…" if e < len(text) else ""))
        if len(hits) >= 5:
            break
    return hits


def _consecutive_same_opening(text, need=3, window=6):
    """连续 window 句中 ≥need 句以相同前两字开头（排比倾向）。"""
    sentences = [s.strip() for s in re.split(r"[。！？\n]+", text) if len(s.strip()) >= 4]
    for i in range(len(sentences) - need + 1):
        heads = [sentences[i + k][:2] for k in range(need)]
        if len(set(heads)) == 1:
            frag = "".join(sentences[i:i + need])[:60]
            return [("…" if i > 0 else "") + frag + "…"]
    return []


def run_checks(text, active_skills=None):
    """对 text 执行所有「已激活且可确定性检测」的技能检查。

    Returns:
        {"passed": bool, "checks": [{"skill","name","passed","violations":[...]}]}
    """
    if active_skills is None:
        from app.services.skill_system import get_active_skills
        try:
            active_skills = get_active_skills()
        except Exception:
            active_skills = []

    active = set(active_skills or [])
    checks = []

    def add(skill_key, name, violations):
        checks.append({
            "skill": skill_key,
            "name": name,
            "passed": not violations,
            "violations": violations,
        })

    # 对话修饰语（两个对话技能共用同一检测）
    if "dialogue_realism" in active or "dialogue_humanize" in active:
        add("dialogue_realism", "对话修饰语", _count_dialogue_modifiers(text))

    # 排比与匀称节奏
    if "rhythm_breaking" in active:
        v = _PARALLEL_TRIAD_RE.findall(text)
        viol = ([f"疑似三连排比：{p}" for p in v[:3]] if v else [])
        viol += _consecutive_same_opening(text)
        add("rhythm_breaking", "排比/匀称句式", viol)

    # 模板结构标记
    if "deai_structure" in active:
        marks = _TEMPLATE_STRUCTURE_RE.findall(text)
        viol = []
        if len(marks) >= 2:
            viol.append(f"出现 {len(marks)} 处「首先/其次/最后」式推进词：" +
                        "、".join(marks[:6]))
        viol += [f"段末/句末总结腔：{x}" for x in
                 _excerpts(text, re.compile(r"总之|综上所述|这就是所谓"))]
        add("deai_structure", "模板结构标记", viol)

    # 段末升华
    if "imperfection" in active:
        tail = text[-400:] if len(text) > 400 else text
        viol = _excerpts(tail, _ENDING_UPLIFT_RE, limit=3)
        add("imperfection", "结尾升华句", viol)

    # 直述情绪标签
    if "show_dont_tell" in active:
        add("show_dont_tell", "直述情绪标签",
            _excerpts(text, _TELL_EMOTION_RE, limit=4))

    # 抽象感官词
    if "sensory_concrete" in active or "sensory_detail" in active:
        add("sensory_concrete", "抽象感官词",
            _excerpts(text, _ABSTRACT_SENSORY_RE, limit=4))

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
    }


def run_gate(text, active_skills=None):
    """run_checks 的别名（对外语义名）。"""
    return run_checks(text, active_skills=active_skills)
