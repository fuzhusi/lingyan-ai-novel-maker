"""AI Tone Metric — 篇章层 AI 痕迹确定性检测（零 LLM 成本）。

规则来源：lieflat-less-ai-tone 283 万字对照语料研究（300 篇五模型生成 vs
329 篇人类文本，频率比 R≥2 才纳入），详见 docs/ai-tone-research.md。

与 deai_agent 的分工：
- deai_agent：词汇层「自动替换」（写后清洗）
- 本模块：篇章层「只检测不修改」，违规带摘录供定向修复闭环使用

小说体裁适配：
- 「序数词当小标题」不适用，未收录
- 「过长前置定语」正则算子在该研究中自身即失败案例，未收录
- 「跨段措辞重复」「相邻句同款密度」阈值含灵砚实测校准点（朱雀 44% 样本）
- 统计指标（句长 CV 等）仅信息性展示不计分——现有公开研究结论互相矛盾，
  待朱雀标注数据校准后再纳入评分
"""
import logging
import os
import re
from collections import Counter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 触发标记定义
# ---------------------------------------------------------------------------

# 1. 翻案腔（R=3.4）——先立误解再推翻的固定句式家族
_REVERSAL_RE = re.compile(
    r"不是[^。！？\n]{1,18}而是|并非[^。！？\n]{1,18}而是"
    r"|不在于[^。！？\n]{1,18}而在于|与其说[^。！？\n]{1,18}不如说"
    r"|看似[^。！？\n]{1,18}实则|表面[^。！？\n]{1,14}实际上?"
    r"|你以为[^。！？\n]{1,18}其实|说到底[，,]"
)

# 2. 顿号并列过密（R=1.8）：单分句内 ≥2 个顿号（三项以上并列）
_DUNHAO_MIN = 2

# 4. 破折号揭晓式（R=3.0；DeepSeek 生成 5.16‰ vs 人类 0.80‰）
_DASH_PER_1K_THRESHOLD = 1.2

# 5a. 提示语冒号（R=3.8）
_PROMPT_COLON_RE = re.compile(
    r"(?:一句话总结|核心是|关键在于|原因如下|原因是|结论是?|本质上是?|"
    r"换句话说|问题的?答案|答案很简单|只有一个原因)[:：]"
)

# 5b. 译文腔五种（R=2.6–5.3 中成立的四种）
_TRANSLATIONESE = [
    ("「当…时」前置从句",
     re.compile(r"当[^，。！？\n]{6,40}时[，,]")),
    ("前置话题壳",
     re.compile(r"(?:^|[。！？\n」])(?:对于|对)[^，。！？\n]{2,12}(?:来说|而言)[，,]")),
    ("句首连接词路标",
     re.compile(r"(?:^|[。！？\n」])(?:然而|因此|此外|与此同时|换言之|总而言之)[，,]")),
    ("「这意味着」复述句",
     re.compile(r"(?:^|[。！？\n」])这(?:意味着|表明|说明)[，,.]?")),
]

# 9. 禁用起手式（R=3.2）
_OPENERS_RE = re.compile(r"说白了[，,]?|说穿了[，,]?|先说结论[，,:：]?")

# 11. 段首零回指评论（R=4.4，区分力最强）
_PARA_OPEN_COMMENT_RE = re.compile(
    r"^(?:听起来|看起来|说白了|值得注意的是|更重要的是|更关键的是|"
    r"关键在于|问题在于|意味着|不难看出|显然|当然|可以说|某种程度上)"
)
ANTECEDENT_MARKS = ("这", "那", "其", "此", "上面", "前面", "它")

# 7. 拟人化理想化喻体（R=7.3；带褒义修饰时 12.6）
_PERSONA_TENOR_RE = re.compile(
    r"(?:像|如同|仿佛|宛如|好比)(?:一[个位]|某个)?"
    r"(?:智慧的?|聪明的|永不?(?:疲倦|疲惫|停歇)(?:的)?|全能的?|尽职的?|"
    r"忠诚的?|沉默的?|冷峻的?)?"
    r"(?:导师|教师|老师傅?|秘书|管家|助手|顾问|审查员|守门人|守护者|"
    r"裁判|法官|长者|智者|引路人|摆渡人)"
)

# 8. 相邻句结构同款：相邻两句逗号数相同且长度接近（连续 ≥2 组判定）
_SAME_STRUCT_LEN_TOL = 0.25

# 门禁扫描上限
_MAX_SCAN_CHARS = 300_000


# ---------------------------------------------------------------------------
# 分句 / 分段工具
# ---------------------------------------------------------------------------

def _split_sentences(text):
    """按 。！？… 切句，保留长度≥4 的句子（含标点）。"""
    parts = re.split(r"([。！？…]+)", text)
    sentences = []
    i = 0
    while i < len(parts):
        s = parts[i]
        punct = parts[i + 1] if i + 1 < len(parts) else ""
        cleaned = re.sub(r"[。！？…！？\s「」『』\"']", "", s)
        if len(cleaned) >= 4:
            sentences.append(s.strip() + punct)
        i += 2
    return sentences


def _split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*", text) if p.strip()]


def _excerpts(text, matches, limit=4, radius=16):
    out = []
    for m in matches[:limit]:
        s = max(0, m.start() - radius)
        e = min(len(text), m.end() + radius)
        frag = text[s:e].replace("\n", " ")
        out.append(("…" if s > 0 else "") + frag + ("…" if e < len(text) else ""))
    return out


# ---------------------------------------------------------------------------
# 各检测项
# ---------------------------------------------------------------------------

def _check_reversal(text):
    ms = list(_REVERSAL_RE.finditer(text))
    return {
        "name": "翻案腔（不是A而是B 及变体）",
        "risk": "high" if len(ms) >= 3 else ("mid" if ms else "low"),
        "count": len(ms),
        "detail": f"命中 {len(ms)} 处（人类参考 0.22‰ / AI 0.73‰）",
        "excerpts": _excerpts(text, ms),
    }


def _check_dunhao(text):
    clauses = re.split(r"[。！？；：\n]", text)
    hits = [c for c in clauses if c.count("、") >= _DUNHAO_MIN]
    return {
        "name": "顿号并列过密（单分句三项以上罗列）",
        "risk": "high" if len(hits) >= 4 else ("mid" if hits else "low"),
        "count": len(hits),
        "detail": f"{len(hits)} 个分句含 ≥2 顿号",
        "excerpts": [c.strip()[:34] for c in hits[:4]],
    }


def _check_dash(text):
    n_chars = max(len(re.sub(r"\s", "", text)), 1)
    density = text.count("——") / n_chars * 1000
    return {
        "name": "破折号揭晓式用法",
        "risk": "high" if density > 2.0 else ("mid" if density > _DASH_PER_1K_THRESHOLD else "low"),
        "count": text.count("——"),
        "detail": f"密度 {density:.2f}/千字（人类参考 0.80，DeepSeek 生成常超 5）",
        "excerpts": [],
    }


def _check_prompt_colon(text):
    ms = list(_PROMPT_COLON_RE.finditer(text))
    return {
        "name": "提示语冒号（核心是：/答案是：）",
        "risk": "high" if len(ms) >= 3 else ("mid" if ms else "low"),
        "count": len(ms),
        "detail": f"命中 {len(ms)} 处（人类参考 0.08‰）",
        "excerpts": _excerpts(text, ms),
    }


def _check_translationese(text):
    findings = []
    total = 0
    for name, pat in _TRANSLATIONESE:
        ms = list(pat.finditer(text))
        total += len(ms)
        if ms:
            findings.append((name, ms))
    viol = []
    for name, ms in findings:
        frag = _excerpts(text, ms, limit=2)
        viol.append(f"{name} ×{len(ms)}：{frag[0] if frag else ''}")
    return {
        "name": "译文腔（当…时 / 对于…来说 / 句首连接词 / 这意味着）",
        "risk": "high" if total >= 5 else ("mid" if total >= 2 else "low"),
        "count": total,
        "detail": "；".join(f"{n}×{len(m)}" for n, m in findings) or "未命中",
        "excerpts": viol,
    }


def _check_openers(text):
    ms = list(_OPENERS_RE.finditer(text))
    return {
        "name": "禁用起手式（说白了/说穿了/先说结论）",
        "risk": "mid" if ms else "low",
        "count": len(ms),
        "detail": f"命中 {len(ms)} 处",
        "excerpts": _excerpts(text, ms),
    }


def _check_para_open_comment(text):
    paras = _split_paragraphs(text)
    hits = []
    for idx, p in enumerate(paras):
        if idx == 0:
            continue
        head = p[:14]
        m = _PARA_OPEN_COMMENT_RE.match(head)
        if m and not any(k in head for k in ANTECEDENT_MARKS):
            hits.append(p[:30])
    return {
        "name": "段首零回指评论（缺「这」类回指，R=4.4 最强信号）",
        "risk": "high" if len(hits) >= 3 else ("mid" if hits else "low"),
        "count": len(hits),
        "detail": f"{len(hits)} 个段落开头抛评论无回指（改法：补一个「这」字）",
        "excerpts": hits[:4],
    }


def _check_persona_tenor(text):
    ms = list(_PERSONA_TENOR_RE.finditer(text))
    return {
        "name": "拟人化理想化喻体（像一位智慧的导师）",
        "risk": "high" if len(ms) >= 2 else ("mid" if ms else "low"),
        "count": len(ms),
        "detail": f"命中 {len(ms)} 处（具体的人作喻体不算，如「像个老中医」）",
        "excerpts": _excerpts(text, ms),
    }


def _check_same_structure(text):
    """相邻句结构同款（R=2.0）：逗号数相同且长度差 ≤25% 的相邻句对。

    按 lieflat 口径折算为每百段密度：AI≈9.4 处/百段，人类≈4.8。
    本检测器口径更宽（任意等逗号+等长对），阈值相应放宽。
    校准点：朱雀 44% 样本实测 21.7/百段。
    """
    sentences = _split_sentences(text)
    def commas(s):
        return s.count("，")
    pairs = []
    for i in range(len(sentences) - 1):
        a, b = sentences[i], sentences[i + 1]
        la, lb = len(a), len(b)
        if la < 10 or lb < 10:
            continue
        ca, cb = commas(a), commas(b)
        if ca != cb:
            continue
        if abs(la - lb) / max(la, lb) <= _SAME_STRUCT_LEN_TOL:
            pairs.append(f"{a[-18:]} ▸ {b[:18]}")
    para_n = max(len(_split_paragraphs(text)), 1)
    rate = len(pairs) * 100.0 / para_n
    # 短文本段数少，一两对就会把密度撑爆——需同时满足密度与绝对次数
    return {
        "name": "相邻句结构同款（密度/百段）",
        "risk": ("high" if rate > 20 and len(pairs) >= 6 else
                 "mid" if rate > 12 and len(pairs) >= 4 else "low"),
        "count": len(pairs),
        "detail": f"{len(pairs)} 组 · {rate:.1f}/百段（参考：人≈4.8 / AI≈9.4）",
        "excerpts": pairs[:4],
    }


# 跨段三元组重复率（词汇分布指纹）：人≈0.018 / AI≈0.064
# 校准点：朱雀 44% 样本实测 0.0977 —— 高于 AI 均值仍被标红
_CROSS_GRAM_MID = 0.045
_CROSS_GRAM_HIGH = 0.075


def _check_cross_para_repetition(text):
    """跨段三元组重复率 + 重复最狠的片段摘录。

    逐节点生成的典型病：各节点独立生成时反复产出同一构式
    （「了一下」「的时候」类），构成全文级词汇分布指纹。
    """
    paras = _split_paragraphs(text)
    if len(paras) < 2:
        return {"name": "跨段措辞重复", "risk": "low", "count": 0,
                "detail": "段落数不足", "excerpts": []}

    gram_paras = {}
    total = 0
    for idx, p in enumerate(paras):
        chars = re.sub(r"[^\u4e00-\u9fa5]", "", p)
        seen = set()
        for i in range(len(chars) - 2):
            g = chars[i:i + 3]
            if g not in seen:
                seen.add(g)
                gram_paras.setdefault(g, set()).add(idx)
                total += 1
    repeated = {g: ps for g, ps in gram_paras.items() if len(ps) >= 3}
    rate = (sum(len(ps) for ps in repeated.values()) / total) if total else 0

    # 出现在最多段落里的三元组 = 最显眼的指纹
    top = sorted(repeated.items(), key=lambda kv: -len(kv[1]))[:6]

    # 取每个高频三元组的一次出现上下文
    excerpts = []
    for g, ps in top:
        p_idx = sorted(ps)[0]
        para_text = paras[p_idx]
        pos = para_text.find(g[:2])
        s = max(0, pos - 8)
        excerpts.append(f"「{g}」×{len(ps)}段：…{para_text[s:pos + 14]}…")

    return {
        "name": "跨段措辞重复（词汇分布指纹）",
        "risk": "high" if rate >= _CROSS_GRAM_HIGH else ("mid" if rate >= _CROSS_GRAM_MID else "low"),
        "count": len(repeated),
        "detail": f"重复率 {rate:.4f}（人≈0.018 / AI≈0.064），"
                  f"{len(repeated)} 个三元组出现在 ≥3 个段落",
        "excerpts": excerpts,
    }


# ---------------------------------------------------------------------------
# 统计指标（信息性展示，暂不计分——待朱雀标注校准）
# ---------------------------------------------------------------------------

def _statistical_features(text):
    sentences = _split_sentences(text)
    lens = [len(re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", s)) for s in sentences]
    lens = [l for l in lens if l > 0]

    def cv(values):
        if len(values) < 2:
            return None
        mean = sum(values) / len(values)
        if mean == 0:
            return None
        var = sum((v - mean) ** 2 for v in values) / len(values)
        return round(var ** 0.5 / mean, 3)

    stats = {}
    stats["sentence_len_cv"] = cv(lens)
    if lens:
        stats["short_sentence_ratio"] = round(sum(1 for l in lens if l < 10) / len(lens), 3)

    paras = _split_paragraphs(text)
    para_lens = [len(re.sub(r"\s", "", p)) for p in paras]
    stats["paragraph_len_cv"] = cv(para_lens)

    para_cvs = []
    for p in paras:
        ls = [len(re.sub(r"[^\u4e00-\u9fa5]", "", s)) for s in _split_sentences(p)]
        ls = [l for l in ls if l > 0]
        c = cv(ls)
        if c is not None:
            para_cvs.append(c)
    stats["para_inner_sent_cv_avg"] = (
        round(sum(para_cvs) / len(para_cvs), 3) if para_cvs else None
    )

    # 跨段 trigram 重复率
    if len(paras) >= 2:
        grams = []
        for p in paras:
            chars = re.sub(r"[^\u4e00-\u9fa5]", "", p)
            grams.append({chars[i:i + 3] for i in range(len(chars) - 2)})
        counter = Counter()
        for gset in grams:
            for g in gset:
                counter[g] += 1
        repeated = sum(1 for v in counter.values() if v >= 2)
        total_grams = sum(counter.values())
        stats["cross_para_3gram_repeat"] = (
            round(repeated / total_grams, 4) if total_grams else None
        )

    stats["reference"] = {
        "sentence_len_cv": "人类≈0.52-0.67 / AI≈0.32-0.58（两项研究结论冲突，仅展示）",
        "short_sentence_ratio": "人类≈0.25 / AI≈0.03（HC3 校准）",
        "cross_para_3gram_repeat": "人类≈0.018 / AI≈0.064（HC3 校准）",
    }
    return stats


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "para_open_comment": 20,
    "persona_tenor": 15,
    "prompt_colon": 10,
    "dash": 10,
    "translationese": 15,
    "reversal": 10,
    "openers": 5,
    "same_structure": 12,
    "cross_para_repetition": 18,
    "dunhao": 5,
}


def analyze_ai_tone(text):
    """对文本执行篇章层 AI 痕迹检测。

    Returns:
        {
          "passed": bool,          # 是否无 mid/high 风险项
          "human_score": int,      # 0-100，越高越像人写的
          "checks": [...],
          "stats": {...},          # 信息性统计指标
        }
    """
    text = (text or "")[:_MAX_SCAN_CHARS]
    if len(text.strip()) < 200:
        return {"passed": True, "human_score": None, "checks": [], "stats": {},
                "skipped": "文本过短（<200 字），跳过检测"}

    checks = {
        "reversal": _check_reversal(text),
        "dunhao": _check_dunhao(text),
        "dash": _check_dash(text),
        "prompt_colon": _check_prompt_colon(text),
        "translationese": _check_translationese(text),
        "openers": _check_openers(text),
        "para_open_comment": _check_para_open_comment(text),
        "persona_tenor": _check_persona_tenor(text),
        "same_structure": _check_same_structure(text),
        "cross_para_repetition": _check_cross_para_repetition(text),
    }

    deduction = 0
    ordered = []
    # 输出顺序：按风险区分力排序（段首回指最强）
    for key in ("para_open_comment", "persona_tenor", "prompt_colon", "dash",
                "translationese", "reversal", "same_structure",
                "cross_para_repetition", "dunhao", "openers"):
        item = checks[key]
        item["passed"] = item["risk"] == "low"
        ordered.append(item)
        if item["risk"] == "high":
            deduction += _WEIGHTS[key]
        elif item["risk"] == "mid":
            deduction += max(_WEIGHTS[key] // 2, 1)

    human_score = max(0, min(100, 100 - deduction))

    return {
        # passed = 无高风险项（mid 为改进建议，不判失败）
        "passed": all(c["risk"] != "high" for c in ordered),
        "human_score": human_score,
        "checks": ordered,
        "stats": _statistical_features(text),
    }


# ---------------------------------------------------------------------------
# 指令构建：把检测违规转为可注入生成提示词的修正指令（二次生成闭环）
# ---------------------------------------------------------------------------

# 功能字过滤：三元组含功能字才视为「构式」，纯实词组合（如人名）不进禁用清单
_FUNCTION_CHARS = set(
    "的了着是在有不他她它我你您们这那哪个就都也都又再把被和跟对向往与或"
    "但而且于是很太更最还只已曾经将便才即让使从到在上去来中里外前后左右"
)

# 修正文案外置到约束词库动态层：constraint_bank/L2_dynamic.yaml
# （检测命中 → 预写修正文案；新增文案须先有对应确定性检测，没有检测就没有动态约束）
_L2_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "constraint_bank", "L2_dynamic.yaml")
_l2_cache = None  # (文件指纹(mtime,size), entries) —— 改 yaml 即时生效，与词库缓存策略一致

# 检测名关键词 → L2 条目 key。顺序即匹配优先级，一条检测只命中一个条目；
# 「顿号并列过密」「禁用起手式」暂无定向改写价值，维持旧版不生成指令的行为。
_CHECK_KEY_MAP = [
    ("相邻句", "相邻句同款"),
    ("破折号", "破折号滥用"),
    ("冒号", "提示语冒号"),
    ("拟人化", "拟人化理想化喻体"),
    ("翻案腔", "翻案腔"),
    ("译文腔", "译文腔"),
    ("段首零回指", "段首零回指评论"),
]


def _load_tone_templates():
    """加载 L2 动态层文案表（文件指纹缓存，改 yaml 即时生效）。

    加载失败返回空表并告警停用指令生成；文件缺失同样返回空表。
    """
    global _l2_cache
    try:
        fingerprint = (os.path.getmtime(_L2_PATH), os.path.getsize(_L2_PATH))
    except OSError:
        logger.warning("L2_dynamic.yaml 不可读，行文指纹修正指令停用",
                       exc_info=True)
        return {}
    if _l2_cache is not None and _l2_cache[0] == fingerprint:
        return _l2_cache[1]
    try:
        import yaml
        with open(_L2_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        entries = data.get("entries") or {}
    except Exception:
        logger.warning("L2_dynamic.yaml 解析失败，行文指纹修正指令停用",
                       exc_info=True)
        entries = {}
    _l2_cache = (fingerprint, entries)
    return entries


def build_tone_instructions(text):
    """对已有正文跑检测，生成注入 Writer/节点提示词的修正指令块。

    用法：二次生成（续写/逐节点/评审重写）时，取已完成文本调用本函数，
    把返回值追加到提示词——模型在写新内容时会主动避开已形成的指纹。
    无违规或文本过短时返回空串。
    文案来源：constraint_bank/L2_dynamic.yaml（检测名关键词映射）。
    """
    rep = analyze_ai_tone(text)
    if rep.get("human_score") is None:
        # 只在无报告（文本过短等）时返回空；score=0 是违规最严重的文本，
        # 恰恰最需要修正指令，绝不能被 falsy 判断吞掉
        return ""

    entries = _load_tone_templates()
    lines = []
    for c in rep["checks"]:
        if c["risk"] == "low":
            continue
        name = c["name"]
        entry = None
        kwargs = {}
        if "跨段措辞重复" in name:
            grams = []
            for ex in c.get("excerpts")[:8]:
                m = re.match(r"「(.+?)」", ex)
                if m and any(ch in _FUNCTION_CHARS for ch in m.group(1)):
                    grams.append(m.group(1))
            if not grams:
                continue
            uniq = list(dict.fromkeys(grams))[:6]
            kwargs["grams"] = "、".join(f"「{g}」" for g in uniq)
            entry = entries.get("跨段措辞重复")
        else:
            for keyword, key in _CHECK_KEY_MAP:
                if keyword in name:
                    entry = entries.get(key)
                    break
        if not entry:
            continue
        template = entry.get("template") if isinstance(entry, dict) else str(entry)
        if not template:
            continue
        try:
            lines.append(template.format(**kwargs))
        except (KeyError, IndexError):
            lines.append(template)

    if not lines:
        return ""
    return ("【行文指纹修正指令 — 对前文检测得出，最高优先级遵守】\n"
            + "\n".join(f"- {ln}" for ln in lines))
