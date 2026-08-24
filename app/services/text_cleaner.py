"""Post-processing for AI-generated text — clean up formatting artifacts."""

import re

# 编号列表标记的序号上限：正文里 "1995. 那一年…" 这种年份开头的句子
# 不是列表，绝不能当列表标记删掉序号
_MAX_LIST_NUMBER = 99

_NUM_LIST_RE = re.compile(r"^(\s*)(\d{1,3})\.\s+")
_BOLD_STAR_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_BOLD_ULINE_RE = re.compile(r"(?<!_)_([^_\n]+)_(?!_)")
_ITALIC_PAIR_STAR_RE = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")


def clean_ai_text(text):
    """Clean up AI-generated text by removing formatting artifacts.

    Handles:
    - Markdown headings (# ## ### etc.)
    - Bold/italic markers (** __ * _) — 仅成对出现时剥离
    - Code blocks (``` `` `)
    - Horizontal rules (--- ___ ***)
    - Bullet markers (- * + at line start)
    - Numbered list markers (1. 2. etc. at line start，序号 < 100)
    - Excessive blank lines
    - Leading/trailing whitespace per line
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned = []

    for line in lines:
        # Remove markdown headings: # Title → Title
        line = re.sub(r"^#{1,6}\s+", "", line)

        # Remove horizontal rules: --- ___ ***
        if re.match(r"^[-*_]{3,}\s*$", line):
            continue

        # Remove bold/italic markers。
        # 成对优先：**x** / __x__ / 单星单下划线；要求两侧紧邻非同类符号，
        # 避免把数学/拟声里的孤立 * _（"他划了一条___"）误删
        line = _BOLD_STAR_RE.sub(r"\1", line)
        line = _BOLD_ULINE_RE.sub(r"\1", line)
        line = _ITALIC_PAIR_STAR_RE.sub(r"\1", line)

        # Remove inline code
        line = re.sub(r"`(.+?)`", r"\1", line)

        # Remove bullet markers at line start
        line = re.sub(r"^\s*[-*+]\s+", "", line)

        # Remove numbered list markers at line start（仅小序号）。
        # 大序号（≥100，如年份"1995. …"）是叙述句开头，保留原样
        m = _NUM_LIST_RE.match(line)
        if m and int(m.group(2)) <= _MAX_LIST_NUMBER:
            line = m.group(1) + line[m.end():]

        # Remove chapter markers like 【第X章】 or 第X章 at line start
        # Keep the content but clean up the brackets
        line = re.sub(r"^【第(\d+)章】\s*", r"第\1章 ", line)

        cleaned.append(line.rstrip())

    # Join and collapse multiple blank lines to max 2
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()
