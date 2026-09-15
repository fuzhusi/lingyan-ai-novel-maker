"""写作链公共层（P3/P4）——generate_stream 与 chapter_runner 的单一实现。

写作包契约（WritingPacket，docs/agent-collaboration.md §3.1）：
    build_writer_kwargs() 是写作链唯一取料入口——上下文组装、预算压缩、
    文风锚例、罗盘、tone 指令、风格备忘录、偏好档案全部在此汇合，
    任何新增注入维度只改这一处，禁止调用方各自拼 prompt。
"""
import json
import logging
import time

from app import db
from app.models import Novel, Setting
from app.services.llm import stream_llm_tokens, LLMError
from app.services.prompt_builder import (
    assemble_chapter_context, apply_context_budget,
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
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # Vector memory context
    try:
        from app.services.vector_memory import build_context_for_chapter
        kw["memory_context"] = build_context_for_chapter(novel_id, chapter_number, outline)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # 叙事计划块(拆书蓝图计划值):must_payoff 伏笔/禁埋令/本章登场退场角色。
    # 小块(~几百字),不参与预算压缩——排程任务是硬约束。
    try:
        from app.services.narrative_plan import build_plan_block
        kw["narrative_plan"] = build_plan_block(novel_id, chapter_number)
    except Exception as exc:
        logger.warning("writer_chain 计划块注入降级: %s", exc)

    # 语义检索(资源库):用本章大纲向量检索对标书相关片段,注入"原书写法参考"。
    # 只取 top-3、每条截 300 字(~900 字),不挤占主上下文预算。
    try:
        from app.services.resource_service import semantic_search
        hits = semantic_search(outline or "", novel_id=novel_id, top_k=3)
        if hits:
            ref_lines = [f"- {h['title']}（{h['resource_title']}）：{h['content'][:200]}"
                         for h in hits if h["score"] > 0.3]
            if ref_lines:
                kw["reference_passages"] = "\n".join(ref_lines)
    except Exception as exc:
        logger.warning("writer_chain 语义检索降级: %s", exc)

    # 语义选角色/设定(实体嵌入):用本章大纲+前文尾部检索相关实体,
    # 替代"全量注入→压缩"——只注入语义相关的 top-K 角色/世界观。
    # 注意：用户显式勾选了出场角色（character_ids 非 None）时跳过角色侧剪枝——
    # 勾选是作者对本章人物的有意安排，不能被语义 top-K 静默裁掉。
    try:
        from app.services.semantic_service import select_relevant_entities
        selected = select_relevant_entities(
            novel_id, outline or "", (ctx.get("prev_ending") or "")[-500:], top_k=5)
        if selected["character_ids"] and character_ids is None:
            char_ids = set(selected["character_ids"])
            kw["characters"] = [c for c in kw["characters"] if c.get("id") in char_ids]
        if selected["world_ids"]:
            world_ids = set(selected["world_ids"])
            kw["world_settings"] = [w for w in kw["world_settings"] if w.get("id") in world_ids]
    except Exception as exc:
        logger.warning("writer_chain 语义选角色降级(回退全量): %s", exc)

    # 信息边界 + 时序真相（一致性红线）：独立字段而非拼进 memory_context，
    boundary_parts = []
    try:
        from app.services.info_boundary import format_knowledge_boundaries
        boundary_ctx = format_knowledge_boundaries(novel_id, chapter_number)
        if boundary_ctx:
            boundary_parts.append(boundary_ctx)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)
    try:
        from app.services.temporal_truth import format_truths_for_prompt
        truth_ctx = format_truths_for_prompt(novel_id, chapter_number)
        if truth_ctx:
            boundary_parts.append(truth_ctx)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)
    if boundary_parts:
        kw["boundary_context"] = "\n\n".join(boundary_parts)

    # 上下文预算渐进压缩：必须在文风锚例注入之前执行（锚例豁免预算）
    try:
        shrink_log = apply_context_budget(kw)
        if shrink_log:
            logger.info("context budget shrink: %s", shrink_log)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

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
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

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
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # P4 风格备忘录（B3）：审批时逐章累积的文体要点，注入最近 3 条
    try:
        memos = json.loads(novel.style_memo_json or "[]") if novel else []
        recent = [m.get("note", "") for m in (memos or [])[-3:]
                  if isinstance(m, dict) and m.get("note")]
        if recent:
            kw["style_memo"] = "\n".join(f"- {m}" for m in recent)
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    # P4 创作偏好档案：结构化的文风/禁忌/受众长期约束
    try:
        pref = Setting.query.get("creator_preferences")
        if pref and (pref.value or "").strip():
            kw["creator_preferences"] = pref.value.strip()
    except Exception as exc:
        logger.warning("writer_chain 上下文注入降级: %s", exc)

    return kw, novel


def _round_tokens(messages, cfg, max_tokens, collected, on_event=None,
                  round_no=1):
    """单轮生成的原始 token 流（附带续写循环共用的收集器）。

    on_event: 可选回调，接收阶段事件 dict（轮次起止/首字延迟），供 SSE
    进度帧与编排器日志使用。回调异常一律吞掉，绝不影响生成主链路。
    """
    started = time.time()
    first_at = None

    def _emit(ev):
        if on_event is None:
            return
        try:
            on_event(ev)
        except Exception:
            pass

    _emit({"stage": "round_start", "round": round_no})
    try:
        for token in stream_llm_tokens(
            model=cfg["model_name"], messages=messages,
            api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""),
            provider_type=cfg.get("provider_type", "deepseek"),
            temperature=cfg.get("temperature", 0.8),
            max_tokens=max_tokens,
            frequency_penalty=cfg.get("frequency_penalty"),
            presence_penalty=cfg.get("presence_penalty"),
        ):
            if first_at is None:
                first_at = time.time()
                _emit({"stage": "first_token", "round": round_no,
                       "ttft_s": round(first_at - started, 1),
                       "model": cfg.get("model_name", ""),
                       "provider": cfg.get("provider_type", "")})
            collected.append(token)
            yield token
    finally:
        # chars 为全章累计（collected 跨轮共享），非本轮新增——前端按轮展示的是
        # 总字数曲线，语义如此；round_no 用于区分是哪一轮结束
        _emit({"stage": "round_end", "round": round_no,
               "chars": len("".join(collected)),
               "elapsed_s": round(time.time() - started, 1)})


def generation_tokens(messages, cfg, word_target=None, on_event=None):
    """完整正文生成的原始 token 流（含字数不足续写轮）。

    on_event: 可选回调，接收进度事件（见 _round_tokens）：
        round_start{round} / first_token{round,ttft_s,model,provider} /
        round_end{round,chars,elapsed_s} / continue_start{round,current_chars,floor}
    SSE 路由与编排器共用的单一实现；LLMError 原样抛出由调用方处置。
    """
    collected = []

    def _emit(ev):
        if on_event is None:
            return
        try:
            on_event(ev)
        except Exception:
            pass

    try:
        yield from _round_tokens(messages, cfg, cfg.get("max_tokens", 4096),
                                 collected, on_event=on_event, round_no=1)
        # 字数保障：仅章节生成传入 word_target 时启用
        if word_target:
            rounds = 0
            while (len("".join(collected)) < CHAPTER_WORD_FLOOR
                   and rounds < CHAPTER_MAX_CONTINUE_ROUNDS):
                rounds += 1
                full = "".join(collected)
                remaining = word_target - len(full)
                _emit({"stage": "continue_start",
                       "round": rounds + 1,
                       "current_chars": len(full),
                       "floor": CHAPTER_WORD_FLOOR})
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
                                         min(remaining * 2, 16000), collected,
                                         on_event=on_event, round_no=rounds + 1)
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
