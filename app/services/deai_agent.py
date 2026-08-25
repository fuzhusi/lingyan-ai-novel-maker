"""De-AI Agent — removes LLM writing artifacts and adds human-like quality.

Inspired by show-me-the-story (23 banned patterns) and knowrite (Author Fingerprint).

Five-pass processing:
1. Banned pattern removal — replace AI-specific phrases
2. Sentence rhythm fix — break monotonous patterns
3. Colloquial polish — add natural human voice
4. Sentence structure fixes
5. Paragraph flow fixes

Total: 120+ banned patterns across 8 categories.
"""

import re
from app.services.deai_patterns import (
    BANNED_FILLER_WORDS, BANNED_EMOTIONAL, BANNED_ADVERBS,
    BANNED_PATTERNS_DESC, BANNED_DIALOGUE, BANNED_TRANSITIONS,
    BANNED_EXPLANATORY, BANNED_IDIOMS,
    BANNED_REPLACEMENTS, BANNED_PATTERNS, COLLOQUIAL_RULES,
)


# ---------------------------------------------------------------------------
# Pass 2: Sentence rhythm patterns (句式节奏)
# ---------------------------------------------------------------------------

def _fix_sentence_rhythm(text):
    """Break monotonous sentence patterns."""
    # 开头重复时允许剥离的词白名单：只剥离话语连接词，
    # 名词/代词主语（他/她/林晚/刀光）被剥离会产出无主残句
    _STRIPPABLE_OPENERS = {"然后", "接着", "于是", "突然", "这时", "随后",
                           "立刻", "马上", "顿时", "瞬间", "终于", "还是", "又"}
    lines = text.split("\n")
    fixed = []

    for line in lines:
        if not line.strip():
            fixed.append(line)
            continue

        sentences = re.split(r'([。！？…]+)', line)
        new_sentences = []

        for i in range(0, len(sentences), 2):
            sent = sentences[i]
            punct = sentences[i + 1] if i + 1 < len(sentences) else ""

            # Fix: consecutive sentences starting with same word
            if new_sentences:
                prev_sent = new_sentences[-1]
                prev_words = re.findall(r'[一-鿿]+', prev_sent[:6])
                curr_words = re.findall(r'[一-鿿]+', sent[:6])
                if (prev_words and curr_words and prev_words[0] == curr_words[0]
                        and curr_words[0] in _STRIPPABLE_OPENERS
                        and len(sent) > len(curr_words[0])):
                    sent = sent[len(curr_words[0]):]

            # Fix: sentences that are too similar in length (±3 chars)
            if new_sentences:
                prev_len = len(new_sentences[-1])
                if abs(len(sent) - prev_len) < 3 and len(sent) > 15:
                    if len(sent) > prev_len:
                        sent = re.sub(r'(\w{2,4})的(?=\w{2,4}的)', '', sent, count=1)

            # Fix: too many "的" in one sentence
            de_count = sent.count("的")
            if de_count > 3:
                sent = re.sub(r'(\w{2,4})的(\w{2,4})的', r'\1\2', sent, count=1)

            # Fix: too many "了" in one sentence
            le_count = sent.count("了")
            if le_count > 2:
                sent = re.sub(r'了(\w{2,4})了', r'\1了', sent, count=1)

            new_sentences.append(sent + punct)

        fixed.append("".join(new_sentences))

    return "\n".join(fixed)


# ---------------------------------------------------------------------------
# Pass 4: Sentence structure fixes (句式结构修复)
# ---------------------------------------------------------------------------
# 2026-08 停用比喻简化规则（像X一样→X 等 8 条）：
# 283 万字对照语料研究（docs/ai-tone-research.md §四）实测人类使用比喻的频率
# 是 AI 的 2.4 倍，比喻独立成段为 8 倍——删比喻是在抹掉人类写作标志特征。
# 比喻治理仅保留一处：拟人化理想化喻体（"像一位智慧的导师"）由 ai_metric 检测，
# 不做自动替换。

def _fix_sentence_structure(text):
    """保留占位以维持五步管线结构；原比喻简化规则已停用。"""
    return text


# ---------------------------------------------------------------------------
# Pass 5: Paragraph flow fixes (段落流畅度修复)
# ---------------------------------------------------------------------------

def _fix_paragraph_flow(text):
    """Fix paragraph-level flow issues."""
    paragraphs = text.split("\n\n")
    fixed = []

    for para in paragraphs:
        if not para.strip():
            fixed.append(para)
            continue

        if para.startswith("而") and len(para) > 10:
            para = para[1:]
        if para.startswith("但是") and len(para) > 10:
            para = para[2:]
        if para.startswith("然而") and len(para) > 10:
            para = para[2:]
        if para.startswith("不过") and len(para) > 10:
            para = para[2:]
        if para.startswith("可是") and len(para) > 10:
            para = para[2:]
        if para.startswith("只是") and len(para) > 10:
            para = para[2:]

        fixed.append(para)

    return "\n\n".join(fixed)


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def deai_enabled():
    """全局「自动去AI化」开关（Setting 键 deai_auto，缺省开启）。

    设为 "0" 后，保存/生成链路上的 deai_process 调用全部直通原文；
    CLI 显式 --save 去AI化等场景可传 force=True 绕过开关。
    """
    try:
        from app.models import Setting
        row = Setting.query.filter_by(key="deai_auto").first()
        if row is not None:
            return str(row.value).strip() != "0"
    except Exception:
        # 表不存在/无应用上下文时保持默认开启，不阻塞文本处理
        pass
    return True


def deai_process(text, strict=False, force=False):
    """Process text to remove AI artifacts.

    Args:
        text: Input text
        strict: If True, apply all rules aggressively. If False, be conservative.
        force: True 时忽略全局开关强制处理（CLI / 诊断场景）

    Returns:
        Processed text with AI artifacts removed
    """
    if not text:
        return text

    if not force and not deai_enabled():
        return text

    # Pass 1: Banned pattern replacement
    for pattern, replacement in BANNED_REPLACEMENTS:
        text = text.replace(pattern, replacement)

    # Pass 1b: Regex patterns
    for pattern, replacement in BANNED_PATTERNS:
        if callable(replacement):
            text = re.sub(pattern, replacement, text)
        else:
            text = re.sub(pattern, replacement, text)

    # Pass 2: Sentence rhythm
    text = _fix_sentence_rhythm(text)

    # Pass 3: Colloquial polish
    for pattern, replacement in COLLOQUIAL_RULES:
        text = re.sub(pattern, replacement, text)

    # Pass 4: Sentence structure fixes
    text = _fix_sentence_structure(text)

    # Pass 5: Paragraph flow fixes
    text = _fix_paragraph_flow(text)

    # Cleanup: remove double spaces and empty lines
    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def get_deai_stats(original, processed):
    """Compare original and processed text, return change statistics."""
    changes = 0
    for pattern, _ in BANNED_REPLACEMENTS:
        count = original.count(pattern)
        if count > 0:
            changes += count

    for pattern, _ in BANNED_PATTERNS:
        matches = re.findall(pattern, original)
        changes += len(matches)

    return {
        "original_length": len(original),
        "processed_length": len(processed),
        "patterns_found": changes,
        "reduction_pct": round((1 - len(processed) / max(len(original), 1)) * 100, 1),
        "banned_words_count": len(BANNED_REPLACEMENTS),
        "regex_patterns_count": len(BANNED_PATTERNS),
        "colloquial_rules_count": len(COLLOQUIAL_RULES),
    }


def get_banned_patterns_summary():
    """Return a summary of all banned patterns for documentation."""
    return {
        "filler_words": len(BANNED_FILLER_WORDS),
        "emotional": len(BANNED_EMOTIONAL),
        "adverbs": len(BANNED_ADVERBS),
        "patterns_desc": len(BANNED_PATTERNS_DESC),
        "dialogue": len(BANNED_DIALOGUE),
        "transitions": len(BANNED_TRANSITIONS),
        "explanatory": len(BANNED_EXPLANATORY),
        "idioms": len(BANNED_IDIOMS),
        "total_replacements": len(BANNED_REPLACEMENTS),
        "regex_patterns": len(BANNED_PATTERNS),
        "colloquial_rules": len(COLLOQUIAL_RULES),
    }
