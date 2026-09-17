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

# 排比检测（rhythm_breaking）：2026-08 调整——句内三连「有的…有的…」不再报违规。
# 对照语料研究（docs/ai-tone-research.md §四）实测句内同构排比人类比 AI 更高频
# （R=0.61），扣分方向相反；成立的是跨相邻句的结构同构（同头连开，R=2.0），
# 由 _consecutive_same_opening 覆盖。

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
    r"|(?:周围|屋里|房间里)(?:十分|非常|格外|很|异常|出奇)?安静"
)

# 标点硬限（harshaneel/humanize：em-dash 每 300 字 ≤1、分号近零、冒号须跟完整句）
# 门禁级：不挂在技能上，始终检查——确定性、零成本
_MAX_DASH_PER_300 = 1.2
_SEMICOLON_HARD = 8          # 全文分号绝对上限
# 空转冒号：后接不足 8 字即收束。排除：
#   1) 数字:数字（8:30 / 3:1）
#   2) 对白提示语后的短句（他说：好。）——由对话技能管
#   3) 引号内的冒号
_COLON_NO_SENTENCE_RE = re.compile(
    r"(?<!\d)[：:](?!\d)(?![^。！？\n」”\"]{8,})"
)
# 对白提示语：动词紧贴冒号（他说：/ 她问： / 老头道：）
# 不用宽匹配——「答案」「知道」里的 答/道 会误伤总结腔冒号
_DIALOGUE_COLON_RE = re.compile(
    r"(?:说|问道|喊道|叫道|答道|吼道|叹道|骂道|笑道|哼道|回道|应道|问|喊|叫|吼|叹|骂|笑|哼)[：:]"
)

# 门禁扫描的最大文本长度（防御性上限，超长截断后仍可检查）
_MAX_SCAN_CHARS = 300_000


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
    """对话修饰语摘录（复用 _excerpts，半径略小以贴近对白本身）。"""
    return _excerpts(text, _DIALOGUE_MODIFIER_RE, limit=5, radius=14)


def _consecutive_same_opening(text, need=3):
    """连续 need 句以相同前两字开头（排比倾向）。

    排除领属语开头（他的/她的/云的…）——「他的手。他的刀。他的命。」
    属于合法的碎句修辞，不算排比违规。
    """
    sentences = [s.strip() for s in re.split(r"[。！？\n]+", text) if len(s.strip()) >= 4]
    for i in range(len(sentences) - need + 1):
        heads = [sentences[i + k][:2] for k in range(need)]
        if len(set(heads)) == 1 and not heads[0].endswith("的"):
            frag = "".join(sentences[i:i + need])[:60]
            return [("…" if i > 0 else "") + frag + "…"]
    return []


def _punctuation_hard_limits(text):
    """标点硬限：破折号密度 / 分号绝对数 / 空转冒号。始终检查。"""
    viol = []
    n_chars = max(len(re.sub(r"\s", "", text)), 1)
    dash_density = text.count("——") / n_chars * 1000
    if dash_density > _MAX_DASH_PER_300:
        viol.append(f"破折号密度 {dash_density:.2f}/千字（硬限 {_MAX_DASH_PER_300}）")
    semis = text.count("；") + text.count(";")
    if semis > _SEMICOLON_HARD:
        viol.append(f"分号 {semis} 处（硬限 {_SEMICOLON_HARD}）")
    empty_colons = []
    for m in _COLON_NO_SENTENCE_RE.finditer(text):
        # 对白提示语冒号不算空转
        start = max(0, m.start() - 12)
        window = text[start:m.end()]
        if _DIALOGUE_COLON_RE.search(window):
            continue
        s = max(0, m.start() - 10)
        e = min(len(text), m.end() + 16)
        frag = text[s:e].replace("\n", " ")
        if "「" in frag or "“" in frag or "』" in frag:
            continue
        empty_colons.append(("…" if s > 0 else "") + frag + ("…" if e < len(text) else ""))
        if len(empty_colons) >= 6:
            break
    if len(empty_colons) >= 3:
        viol.append(f"空转冒号 {len(empty_colons)} 处（冒号后须跟完整句）")
    return viol


def run_checks(text, active_skills=None):
    """对 text 执行所有「已激活且可确定性检测」的技能检查。

    Returns:
        {"passed": bool, "checks": [{"skill","name","passed","violations":[...]}]}
    """
    text = (text or "")[:_MAX_SCAN_CHARS]
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

    # 排比与匀称节奏（仅跨句同构；句内排比不判）
    if "rhythm_breaking" in active:
        viol = _consecutive_same_opening(text)
        add("rhythm_breaking", "跨句同构排比", viol)

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

    # 标点硬限（始终检查，不依赖技能激活）
    punct_viol = _punctuation_hard_limits(text)
    add("punctuation_limits", "标点硬限", punct_viol)

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
    }


def run_gate(text, active_skills=None):
    """run_checks 的别名（对外语义名）。"""
    return run_checks(text, active_skills=active_skills)
