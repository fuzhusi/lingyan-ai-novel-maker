"""去AI味收敛回滚环 + 字数超标压缩。

收敛环（借鉴 jarvis-write，见 docs/merge-assessment.md A2）：
    检测(ai_metric) → 定向重写(违规指令注入) → 复测 → 人味分不升则回滚。
    「绝不保留更差版本」：任何一轮重写产物只要人味分未超过历史最优，一律丢弃。

压缩 pass（merge-assessment A5）：字数保障只管"不足续写"的下限，
本模块补"超标压缩"的上限——保留全部情节节拍/对话/因果，压描写冗余。
"""
import logging

from app.services.ai_metric import analyze_ai_tone, build_tone_instructions
from app.services.llm import call_llm_sync, LLMError

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 2          # 单次收敛最多重写轮数（每轮都要真实调用，贵）
_MIN_LEN = 200           # 产物低于此长度视为失败（analyze 的最小可测长度）
_CLEAN_SCORE = 95        # 达到即视为干净，提前终止

_REWRITE_SYSTEM = (
    "你是一位小说稿件的定向修整编辑。只修复指出的 AI 痕迹问题，"
    "最大限度保留原文的情节、对话、意象与人味表达；"
    "禁止扩写情节、禁止美化文字、禁止改变叙事顺序与人物语气。"
    "未被点名的句子必须逐字保留。只输出修改后的完整正文。")

_CONDENSE_SYSTEM = (
    "你是一位小说稿件的压缩编辑。在完整保留全部情节节拍、对话关键信息与"
    "因果推进的前提下，压缩环境描写、心理独白与重复修饰，把正文控制在"
    "目标字数附近。禁止删除情节点，禁止改变叙事顺序。只输出压缩后的完整正文。")


def converge_tone(text, cfg, max_rounds=_MAX_ROUNDS):
    """去AI味收敛回滚环。

    Args:
        text: 待收敛正文。
        cfg: effective config（rewrite Agent 配置，模型要能承担整章重写）。
        max_rounds: 最多重写轮数。

    Returns:
        {"converged": bool, "text": str,       # converged=False 时 text 为原稿
         "original_score": int|None, "final_score": int|None,
         "rounds": [{round, action, score?}], "reason": str}   # reason 仅失败时
    """
    text = (text or "").strip()
    report = analyze_ai_tone(text)
    if report.get("human_score") is None:
        return {"converged": False, "text": text,
                "original_score": None, "final_score": None, "rounds": [],
                "reason": report.get("skipped", "文本过短，跳过检测")}

    original_score = report["human_score"]
    best_text, best_score = text, original_score
    rounds = []

    for r in range(1, max_rounds + 1):
        if best_score >= _CLEAN_SCORE and analyze_ai_tone(best_text)["passed"]:
            rounds.append({"round": r, "action": "已达标，提前结束"})
            break
        instructions = build_tone_instructions(best_text)
        if not instructions:
            rounds.append({"round": r, "action": "无可定向的违规指令，结束"})
            break
        user = (f"【原文】\n{best_text}\n\n"
                f"【必须修复的 AI 痕迹（含违规示例）】\n{instructions}\n\n"
                "【要求】输出修复后的完整正文。未命中问题的句子逐字保留；"
                "除修复项外不做任何改动。")
        try:
            rewritten = call_llm_sync(
                model=cfg["model_name"], messages=[
                    {"role": "system", "content": _REWRITE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
                provider_type=cfg.get("provider_type", "deepseek"),
                temperature=0.4, max_tokens=cfg.get("max_tokens", 8000))
        except LLMError as e:
            rounds.append({"round": r, "action": f"重写调用失败：{e}"})
            break
        rewritten = (rewritten or "").strip()
        if len(rewritten) < _MIN_LEN:
            rounds.append({"round": r, "action": "重写产物过短，弃用"})
            break

        new_score = analyze_ai_tone(rewritten).get("human_score")
        if new_score is not None and new_score > best_score:
            rounds.append({"round": r, "action": "人味分提升，采纳",
                           "score": new_score})
            best_text, best_score = rewritten, new_score
        else:
            # 回滚纪律：绝不保留更差版本
            rounds.append({"round": r, "action": "人味分未提升，回滚保留原稿",
                           "score": new_score})
            break

    return {
        "converged": best_score > original_score,
        "text": best_text,
        "original_score": original_score,
        "final_score": best_score,
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
        result = call_llm_sync(
            model=cfg["model_name"], messages=[
                {"role": "system", "content": _CONDENSE_SYSTEM},
                {"role": "user", "content": user},
            ],
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=0.4, max_tokens=max(cfg.get("max_tokens", 8000),
                                            target_chars * 2))
    except LLMError as e:
        return {"ok": False, "text": text, "reason": str(e)}
    result = (result or "").strip()
    if len(result) < _MIN_LEN or len(result) >= len(text):
        return {"ok": False, "text": text, "reason": "压缩产物不合格（过短或未变短），保留原稿"}
    return {"ok": True, "text": result,
            "original_chars": len(text), "condensed_chars": len(result)}
