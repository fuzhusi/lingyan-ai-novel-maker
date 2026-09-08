"""写作链公共层（P3/P4）——generate_stream 与 chapter_runner 的单一实现。

写作包契约（WritingPacket，docs/agent-collaboration.md §3.1）：
    build_writer_kwargs() 是写作链唯一取料入口——上下文组装、预算压缩、
    文风锚例、罗盘、tone 指令、风格备忘录、偏好档案全部在此汇合，
    任何新增注入维度只改这一处，禁止调用方各自拼 prompt。
"""
import json
import logging

from app import db
from app.models import Novel, Setting
from app.services.llm import stream_llm_tokens, LLMError
from app.services.prompt_builder import (
    build_writer_prompt, assemble_chapter_context, apply_context_budget,
)

logger = logging.getLogger(__name__)

# 章节字数保障：目标约 2500 字，低于底线自动续写补足（对齐短篇的续写模式）
CHAPTER_WORD_TARGET = 2500
CHAPTER_WORD_FLOOR = 2000
CHAPTER_MAX_CONTINUE_ROUNDS = 3


def build_writer_kwargs(novel_id, chapter_number, outline,
                        user_directive="", character_ids=None):
    """组装写作包 kw（供 build_writer_prompt(**kw)）。

    Returns:
        (kw, novel)；novel_id/chapter_number 缺失时返回 ({}, None)。
    """
    if not (novel_id and chapter_number):
        return {}, None

    novel = Novel.query.get(novel_id)

    # 出场角色勾选（前端角色库勾选区）：逗号分隔的角色 id
    # None/缺省 = 全部角色（兼容旧流程与 MCP）；显式空串 = 不注入任何角色档案
    kw = {}
    ctx = assemble_chapter_context(novel_id, chapter_number, db,
                                   character_ids=character_ids)
    kw = {
        "characters": ctx["characters"],
        "world_settings": ctx["world_settings"],
        "summaries": ctx["summaries"],
        "earlier_summaries": ctx["earlier_summaries"],
        "prev_ending": ctx["prev_ending"],
        "foreshadowing_items": ctx["foreshadowing_items"],
        "synopsis": ctx["synopsis"],
        "world_intro": ctx["world_intro"],
        "genre": ctx["genre"],
        "outline_node_context": ctx["outline_node_context"],
        "author_intent": ctx["author_intent"],
        "current_focus": ctx["current_focus"],
    }

    # Causal chain context from previous chapters
    try:
        from app.services.causal_chain import get_chain_context, format_chain_for_prompt
        chains = get_chain_context(novel_id, chapter_number)
        kw["causal_chain"] = format_chain_for_prompt(chains)
    except Exception:
        pass

    # Vector memory context
    try:
        from app.services.vector_memory import build_context_for_chapter
        kw["memory_context"] = build_context_for_chapter(novel_id, chapter_number, outline)
    except Exception:
        pass

    # 信息边界 + 时序真相（一致性红线）：独立字段而非拼进 memory_context，
    # 预算压缩第 4 级会把 memory_context 拦腰截半，边界被切会静默破坏一致性
    boundary_parts = []
    try:
        from app.services.info_boundary import format_knowledge_boundaries
        boundary_ctx = format_knowledge_boundaries(novel_id, chapter_number)
        if boundary_ctx:
            boundary_parts.append(boundary_ctx)
    except Exception:
        pass
    try:
        from app.services.temporal_truth import format_truths_for_prompt
        truth_ctx = format_truths_for_prompt(novel_id, chapter_number)
        if truth_ctx:
            boundary_parts.append(truth_ctx)
    except Exception:
        pass
    if boundary_parts:
        kw["boundary_context"] = "\n\n".join(boundary_parts)

    # 上下文预算渐进压缩：必须在文风锚例注入之前执行（锚例豁免预算）
    try:
        shrink_log = apply_context_budget(kw)
        if shrink_log:
            logger.info("context budget shrink: %s", shrink_log)
    except Exception:
        pass

    # Style fingerprint（注入顺序在预算压缩之后：风格上下文豁免预算）
    try:
        from app.services.style_fingerprint import (
            load_style, format_style_for_prompt, format_anchor_for_prompt)
        style = load_style()
        if style:
            style_ctx = format_style_for_prompt(style)
            if style_ctx:
                existing = kw.get("memory_context", "")
                kw["memory_context"] = (existing + "\n\n" + style_ctx).strip()
        anchor_ctx = format_anchor_for_prompt()
        if anchor_ctx:
            existing = kw.get("memory_context", "")
            kw["memory_context"] = (existing + "\n\n" + anchor_ctx).strip()
    except Exception:
        pass

    # 行文指纹修正指令：基于近期章节正文的 AI 痕迹检测（降 AI 率闭环）
    try:
        from app.models import Chapter as ChapterModel
        from app.services.ai_metric import build_tone_instructions
        recent = (ChapterModel.query
                  .filter(ChapterModel.novel_id == novel_id,
                          ChapterModel.chapter_number < chapter_number)
                  .order_by(ChapterModel.chapter_number.desc())
                  .limit(2).all())
        sample_text = "\n\n".join(ch.content or "" for ch in reversed(recent))
        if len(sample_text.strip()) >= 500:
            tone_inst = build_tone_instructions(sample_text[-15000:])
            if tone_inst:
                kw["tone_instructions"] = tone_inst
    except Exception:
        pass

    # P4 风格备忘录（B3）：审批时逐章累积的文体要点，注入最近 3 条
    try:
        memos = json.loads(novel.style_memo_json or "[]") if novel else []
        recent = [m.get("note", "") for m in (memos or [])[-3:]
                  if isinstance(m, dict) and m.get("note")]
        if recent:
            kw["style_memo"] = "\n".join(f"- {m}" for m in recent)
    except Exception:
        pass

    # P4 创作偏好档案：结构化的文风/禁忌/受众长期约束
    try:
        pref = Setting.query.get("creator_preferences")
        if pref and (pref.value or "").strip():
            kw["creator_preferences"] = pref.value.strip()
    except Exception:
        pass

    return kw, novel


def _round_tokens(messages, cfg, max_tokens, collected):
    """单轮生成的原始 token 流（附带续写循环共用的收集器）。"""
    for token in stream_llm_tokens(
        model=cfg["model_name"], messages=messages,
        api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
        provider_type=cfg.get("provider_type", "deepseek"),
        temperature=cfg.get("temperature", 0.8),
        max_tokens=max_tokens,
        frequency_penalty=cfg.get("frequency_penalty"),
        presence_penalty=cfg.get("presence_penalty"),
    ):
        collected.append(token)
        yield token


def generation_tokens(messages, cfg, word_target=None):
    """完整正文生成的原始 token 流（含字数不足续写轮）。

    SSE 路由与编排器共用的单一实现；LLMError 原样抛出由调用方处置。
    """
    collected = []
    try:
        yield from _round_tokens(messages, cfg, cfg.get("max_tokens", 4096), collected)
        # 字数保障：仅章节生成传入 word_target 时启用
        if word_target:
            rounds = 0
            while (len("".join(collected)) < CHAPTER_WORD_FLOOR
                   and rounds < CHAPTER_MAX_CONTINUE_ROUNDS):
                rounds += 1
                full = "".join(collected)
                remaining = word_target - len(full)
                yield "\n\n"
                continue_messages = [
                    {"role": "system", "content": (
                        "你正在续写一章小说。直接接续前文写下去，"
                        "不要重复已有内容，不要总结前文，不要输出任何说明文字。"
                    )},
                    {"role": "user", "content": (
                        f"【本章已写内容（结尾部分）】\n{full[-3000:]}\n\n"
                        f"【要求】从上文断点直接继续，自然推进本章大纲中的情节，"
                        f"还需写约 {max(remaining, 500)} 字。"
                    )},
                ]
                yield from _round_tokens(continue_messages, cfg,
                                         min(remaining * 2, 16000), collected)
    except LLMError:
        raise
    except Exception as e:
        logger.error("generation_tokens failed: %s", e)
        raise LLMError(f"LLM 调用失败: {e}") from e


def collect_full_text(messages, cfg, word_target=None):
    """非流式消费生成流，返回完整正文（runner 用）。LLMError 向上抛。"""
    parts = []
    for token in generation_tokens(messages, cfg, word_target=word_target):
        parts.append(token)
    return "".join(parts)
