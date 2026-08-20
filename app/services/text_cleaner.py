"""Post-processing for AI-generated text — clean up formatting artifacts."""

import re


def clean_ai_text(text):
    """Clean up AI-generated text by removing formatting artifacts.

    Handles:
    - Markdown headings (# ## ### etc.)
    - Bold/italic markers (** __ * _)
    - Code blocks (``` `` `)
    - Horizontal rules (--- ___ ***)
    - Bullet markers (- * + at line start)
    - Numbered list markers (1. 2. etc. at line start)
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

        # Remove bold/italic markers
        line = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", line)
        line = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", line)

        # Remove inline code
        line = re.sub(r"`(.+?)`", r"\1", line)

        # Remove bullet markers at line start
        line = re.sub(r"^\s*[-*+]\s+", "", line)

        # Remove numbered list markers at line start
        line = re.sub(r"^\s*\d+\.\s+", "", line)

        # Remove chapter markers like 【第X章】 or 第X章 at line start
        # Keep the content but clean up the brackets
        line = re.sub(r"^【第(\d+)章】\s*", r"第\1章 ", line)

        cleaned.append(line.rstrip())

    # Join and collapse multiple blank lines to max 2
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()
