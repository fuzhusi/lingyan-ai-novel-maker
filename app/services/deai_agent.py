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
                if prev_words and curr_words and prev_words[0] == curr_words[0]:
                    if len(curr_words[0]) <= 2 and len(sent) > len(curr_words[0]):
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

def _fix_sentence_structure(text):
    """Fix common AI sentence structures."""
    text = re.sub(r'是(\w{2,6})的', r'\1', text, count=2)
    text = re.sub(r'有(\w{2,6})的', r'\1', text, count=2)
    text = re.sub(r'像(\w{2,6})一样', r'\1', text, count=2)
    text = re.sub(r'如同(\w{2,6})一般', r'\1', text, count=2)
    text = re.sub(r'好像(\w{2,6})似的', r'\1', text, count=2)
    text = re.sub(r'仿佛(\w{2,6})般', r'\1', text, count=2)
    text = re.sub(r'犹如(\w{2,6})般', r'\1', text, count=2)
    text = re.sub(r'宛如(\w{2,6})般', r'\1', text, count=2)
    text = re.sub(r'恰似(\w{2,6})般', r'\1', text, count=2)
    text = re.sub(r'好比(\w{2,6})般', r'\1', text, count=2)
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

def deai_process(text, strict=False):
    """Process text to remove AI artifacts.

    Args:
        text: Input text
        strict: If True, apply all rules aggressively. If False, be conservative.

    Returns:
        Processed text with AI artifacts removed
    """
    if not text:
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
