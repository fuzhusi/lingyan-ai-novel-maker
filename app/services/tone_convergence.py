"""去AI味收敛回滚环 + 字数超标压缩。

收敛环（借鉴 jarvis-write + oh-story story-deslop + 调研 P0 双轨）：
    检测(ai_metric + web_novel_gate) → 定向重写 → 复测 → 分数不升则回滚。
    「绝不保留更差版本」：重写产物只要人味分未超过历史最优（或好看度未升且人味不降），丢弃。

保护纪律：
    - 只改怎么说，不改说什么；允许加强钩子/开场，禁止删情节
    - Jaccard 改动率与长度收缩比双硬顶（阈值见 _DENSITY_CAPS / _LENGTH_SHRINK_CAP）
    - 防「marker 过冲」：短句占比冲到异常高位时视为假人味，弃用
"""
import logging
import re

from app.services.ai_metric import analyze_ai_tone, build_tone_instructions
from app.services.llm import call_llm_auto, LLMError

logger = logging.getLogger(__name__)


def _call_llm_flexible(cfg, messages, temperature, max_tokens):
    """兼容旧名：转发共享的流式优先实现（见 llm.call_llm_auto）。"""
    return call_llm_auto(
        model=cfg["model_name"], messages=messages,
        api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
        provider_type=cfg.get("provider_type", "deepseek"),
        temperature=temperature, max_tokens=max_tokens,
        timeout=cfg.get("timeout") or 600.0)


_MAX_ROUNDS = 2          # 单次收敛最多重写轮数（每轮都要真实调用，贵）
_MIN_LEN = 200           # 产物低于此长度视为失败（analyze 的最小可测长度）
_CLEAN_SCORE = 95        # 达到即视为干净，提前终止

# 删改比例硬顶。注意：_char_edit_ratio 用 2-gram Jaccard 近似，
# 对「同义改写」天然高估（改 10% 句子 Jaccard 改动率可达 ~15-20%）。
# oh-story 的 15/25/35% 是「删除字符占比」口径，不能直接当 Jaccard 阈值。
# 此处按 Jaccard 口径放大一档，并以长度收缩比做二次确认（防大删）。
_DENSITY_CAPS = {"light": 0.35, "mid": 0.50, "heavy": 0.65}
_LENGTH_SHRINK_CAP = {"light": 0.12, "mid": 0.22, "heavy": 0.32}

# 假人味过冲阈值：短句占比超过此值视为把文风雕成第三种文体（朱雀「疑似桶」教训）
_SHORT_RATIO_OVERSHOOT = 0.55

# 内容词（实词骨架）集合，用于「改写不漂移」粗检
_CONTENT_RE = re.compile(r"[一-龥]{2,}")


_REWRITE_SYSTEM = (
    "你是一位小说稿件的定向修整编辑。铁律如下：\n"
    "1. 只改怎么说，不改说什么：情节节拍、人物行为、因果关系、对话信息、"
    "地名人名、数字、时间、否定与程度副词（可能/一定/几乎）必须原样保留。\n"
    "2. 未被点名的句子逐字保留；只修复指出的 AI 痕迹。\n"
    "3. 禁止扩写情节、禁止美化文字、禁止改变叙事顺序与人物语气。\n"
    "4. 禁止为了「像人」而程序化打碎句子、编错别字、强行加俚语。\n"
    "5. 全文删改字符数不得超过原文的给定上限；宁可少改，不可伤文。\n"
    "只输出修改后的完整正文，不要解释。")

_CONDENSE_SYSTEM = (
    "你是一位小说稿件的压缩编辑。在完整保留全部情节节拍、对话关键信息与"
    "因果推进的前提下，压缩环境描写、心理独白与重复修饰，把正文控制在"
    "目标字数附近。禁止删除情节点，禁止改变叙事顺序。只输出压缩后的完整正文。")

def _violation_density(report):
    """按 high 项数量与人味分推断违规密度档：light / mid / heavy。"""
    score = report.get("human_score")
    highs = sum(1 for c in report.get("checks", []) if c.get("risk") == "high")
    if score is None:
        return "light"
    if highs >= 3 or score < 60:
        return "heavy"
    if highs >= 1 or score < 85:
        return "mid"
    return "light"


def _char_edit_ratio(original, rewritten):
    """粗估改动比例：2-gram Jaccard 距离。对同义改写会高估，阈值已按此放大。"""
    def grams(s):
        s = re.sub(r"\s", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}
    ga, gb = grams(original), grams(rewritten)
    if not ga and not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb) or 1
    return round(1.0 - inter / union, 3)


def _length_shrink_ratio(original, rewritten):
    """长度收缩比：(原长-新长)/原长，仅在变短时 >0。对应 oh-story 删除上限口径。"""
    a, b = len(original), len(rewritten)
    if a <= 0:
        return 0.0
    return max(0.0, (a - b) / a)


def _content_preservation(original, rewritten, floor=0.55):
    """实词骨架保留率：改写后应有足够比例的原内容词仍在（防语义漂移）。"""
    def words(s):
        return set(_CONTENT_RE.findall(s))
    wa, wb = words(original), words(rewritten)
    if not wa:
        return 1.0
    return len(wa & wb) / len(wa)


def _overshoot_check(original_report, rewritten_report):
    """防假人味过冲：短句占比从合理区间冲到异常高位 → 判为雕过头。"""
    o = (original_report.get("stats") or {}).get("short_sentence_ratio") or 0
    r = (rewritten_report.get("stats") or {}).get("short_sentence_ratio") or 0
    return r >= _SHORT_RATIO_OVERSHOOT and r > o + 0.15


def converge_tone(text, cfg, max_rounds=_MAX_ROUNDS, outline=""):
    """去AI味收敛回滚环。

    Args:
        text: 待收敛正文。
        cfg: effective config（rewrite Agent 配置，模型要能承担整章重写）。
        max_rounds: 最多重写轮数。
        outline: 可选本章大纲——注入追读结构修正（双轨门禁）。

    Returns:
        {"converged": bool, "text": str,       # converged=False 时 text 为原稿
         "original_score": int|None, "final_score": int|None,
         "density": str, "edit_cap": float,
         "rounds": [{round, action, score?}], "reason": str}   # reason 仅失败时
    """
    text = (text or "").strip()
    report = analyze_ai_tone(text)
    if report.get("human_score") is None:
        return {"converged": False, "text": text,
                "original_score": None, "final_score": None,
                "density": "light", "edit_cap": _DENSITY_CAPS["light"],
                "rounds": [],
                "reason": report.get("skipped", "文本过短，跳过检测")}

    original_score = report["human_score"]
    density = _violation_density(report)
    edit_cap = _DENSITY_CAPS[density]
    best_text, best_score = text, original_score
    best_report = report
    best_read = None
    rounds = []

    for r in range(1, max_rounds + 1):
        # 人味分达标但仍可能追读不达标——两轨都干净才提前结束
        try:
            from app.services.web_novel_gate import analyze_web_novel as _anw
            _r_now = _anw(best_text, outline or "")
        except Exception:
            _r_now = {"passed": True, "readability_score": 100}
        human_clean = (best_score >= _CLEAN_SCORE
                       and analyze_ai_tone(best_text).get("passed"))
        read_clean = bool(_r_now.get("passed")) or (
            (_r_now.get("readability_score") or 0) >= 85)
        if human_clean and read_clean:
            rounds.append({"round": r, "action": "人味+追读均达标，提前结束"})
            break
        instructions = build_tone_instructions(best_text)
        # 追读结构修正（人味分之外的第二轨）
        try:
            from app.services.web_novel_gate import build_readability_instructions
            read_instr = build_readability_instructions(best_text, outline or "")
        except Exception:
            read_instr = ""
        if not instructions and not read_instr:
            rounds.append({"round": r, "action": "无可定向的违规指令，结束"})
            break
        user = (
            f"【原文】\n{best_text}\n\n"
            f"【必须修复的 AI 痕迹（含违规示例）】\n{instructions or '（无构式违规）'}\n\n"
            f"{read_instr or ''}\n\n"
            f"【保护硬顶】\n"
            f"- 只改怎么说，不改说什么；戏剧任务（目标/冲突/钩子）可以加强，不可删除情节\n"
            f"- 全文删改字符比例不得超过 {int(edit_cap * 100)}%\n"
            f"- 地名/人名/数字/时间/否定与程度副词必须原样保留\n"
            f"- 未命中问题的句子逐字保留\n\n"
            f"【要求】输出修复后的完整正文。除修复项外不做任何改动。")
        try:
            rewritten = _call_llm_flexible(
                cfg, [
                    {"role": "system", "content": _REWRITE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.4, max_tokens=cfg.get("max_tokens", 8000))
        except LLMError as e:
            rounds.append({"round": r, "action": f"重写调用失败：{e}"})
            break
        rewritten = (rewritten or "").strip()
        if len(rewritten) < _MIN_LEN:
            rounds.append({"round": r, "action": "重写产物过短，弃用"})
            break

        edit_ratio = _char_edit_ratio(best_text, rewritten)
        shrink = _length_shrink_ratio(best_text, rewritten)
        shrink_cap = _LENGTH_SHRINK_CAP[density]
        if shrink > shrink_cap:
            rounds.append({
                "round": r,
                "action": f"长度收缩 {shrink:.0%} 超过 {density} 档删除上限 {shrink_cap:.0%}，弃用",
                "shrink": shrink,
            })
            break
        if edit_ratio > edit_cap:
            rounds.append({
                "round": r,
                "action": f"改动比例 {edit_ratio:.0%} 超过 {density} 档上限 {edit_cap:.0%}，弃用",
                "edit_ratio": edit_ratio,
            })
            break

        preserve = _content_preservation(best_text, rewritten)
        if preserve < 0.55:
            rounds.append({
                "round": r,
                "action": f"实词保留率 {preserve:.0%} 过低，疑似语义漂移，弃用",
                "preserve": preserve,
            })
            break

        new_report = analyze_ai_tone(rewritten)
        new_score = new_report.get("human_score")
        # 双轨采纳：人味分不降 且（分升 或 好看度升）
        try:
            from app.services.web_novel_gate import analyze_web_novel
            old_r = analyze_web_novel(best_text, outline or "").get("readability_score") or 0
            new_r = analyze_web_novel(rewritten, outline or "").get("readability_score") or 0
        except Exception:
            old_r, new_r = 0, 0
        if _overshoot_check(best_report, new_report):
            rounds.append({
                "round": r,
                "action": "短句占比过冲（假人味），弃用",
                "short_ratio": (new_report.get("stats") or {}).get("short_sentence_ratio"),
            })
            break

        score_up = new_score is not None and new_score > best_score
        read_up = new_r > old_r
        if new_score is not None and (score_up or (read_up and new_score >= best_score)):
            rounds.append({"round": r, "action": "人味/好看度提升，采纳",
                           "score": new_score, "readability": new_r,
                           "edit_ratio": edit_ratio})
            best_text, best_score, best_report = rewritten, new_score, new_report
            best_read = new_r
        else:
            # 回滚纪律：绝不保留更差版本
            rounds.append({"round": r, "action": "人味分未提升，回滚保留原稿",
                           "score": new_score, "readability": new_r})
            break

    try:
        from app.services.web_novel_gate import analyze_web_novel as _anw2
        final_read = _anw2(best_text, outline or "").get("readability_score")
    except Exception:
        final_read = best_read
    orig_read = None
    try:
        from app.services.web_novel_gate import analyze_web_novel as _anw3
        orig_read = _anw3(text, outline or "").get("readability_score")
    except Exception:
        orig_read = None

    return {
        "converged": (best_score > original_score
                      or (final_read is not None and orig_read is not None
                          and final_read > orig_read)),
        "text": best_text,
        "original_score": original_score,
        "final_score": best_score,
        "readability_score": final_read,
        "original_readability": orig_read,
        "density": density,
        "edit_cap": edit_cap,
        "rounds": rounds,
    }


def condense_text(text, cfg, target_chars=2500):
    """字数超标压缩。超过目标 1.3 倍才动手，压不动/压坏了都返回原稿。"""
    text = (text or "").strip()
    threshold = target_chars * 13 // 10
    if len(text) <= threshold:
        return {"ok": False, "text": text,
                "reason": f"未超过压缩阈值（{threshold} 字），无需压缩"}
    user = (f"【原文（约 {len(text)} 字）】\n{text}\n\n"
            f"【要求】压缩到约 {target_chars} 字：保留全部情节节拍、对话关键"
            f"信息与因果推进；压缩环境描写、心理独白与重复修饰。"
            "直接输出压缩后的完整正文。")
    try:
        result = _call_llm_flexible(
            cfg, [
                {"role": "system", "content": _CONDENSE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.4, max_tokens=max(cfg.get("max_tokens", 8000),
                                            target_chars * 2))
    except LLMError as e:
        return {"ok": False, "text": text, "reason": str(e)}
    result = (result or "").strip()
    if len(result) < _MIN_LEN or len(result) >= len(text):
        return {"ok": False, "text": text, "reason": "压缩产物不合格（过短或未变短），保留原稿"}
    # 压缩同样受「不改说什么」保护：实词保留率过低则弃用
    preserve = _content_preservation(text, result)
    if preserve < 0.70:
        return {"ok": False, "text": text,
                "reason": f"压缩后实词保留率 {preserve:.0%} 过低，疑似丢情节，保留原稿"}
    return {"ok": True, "text": result,
            "original_chars": len(text), "condensed_chars": len(result),
            "content_preserve": round(preserve, 3)}
